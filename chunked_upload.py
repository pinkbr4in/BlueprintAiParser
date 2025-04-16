# chunked_upload.py
# --- Phase 1 Refactor: Added DEBUG Logging ---

import os
import time
import uuid
import logging
import json
import redis
import boto3
from botocore.exceptions import ClientError
from flask import request, jsonify, current_app

# --- Import Celery and Tasks ---
try:
    from celery_app import celery
    from tasks import parse_blueprint_task
    UPLOAD_ENABLED = True
    print("INFO (chunked_upload.py): Celery/Task imported.")
except ImportError as import_err:
    print(f"ERROR (chunked_upload.py): Failed to import Celery/Task: {import_err}. Upload disabled.")
    celery = None
    parse_blueprint_task = None
    UPLOAD_ENABLED = False

# --- Helper Functions ---

def _get_logger():
    try:
        return current_app.logger
    except RuntimeError:
        logger = logging.getLogger('chunked_upload')
        if not logger.handlers:
            # Basic setup if outside app context
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG) # Ensure DEBUG level for fallback
        return logger

def get_redis_client():
    logger = _get_logger()
    redis_url = current_app.config.get('REDIS_URL')
    if not redis_url:
        logger.error("REDIS_URL not configured in Flask app.")
        raise ValueError("REDIS_URL not configured in Flask app.")
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        logger.debug("Redis client created and ping successful.")
        return client
    except redis.RedisError as e:
        logger.error(f"Failed to connect to Redis at {redis_url}: {e}")
        raise

def get_s3_client():
    logger = _get_logger()
    endpoint_url = current_app.config.get('R2_ENDPOINT_URL')
    access_key = current_app.config.get('R2_ACCESS_KEY_ID')
    secret_key = current_app.config.get('R2_SECRET_ACCESS_KEY')
    region_name = 'auto' # Use 'auto' region for R2

    if not all([endpoint_url, access_key, secret_key]):
         logger.error("Missing R2/S3 configuration for client (Endpoint, Key ID, Secret Key).")
         raise ValueError("Missing R2/S3 configuration for client.")

    try:
        logger.debug(f"Attempting to create S3 client. Endpoint: {endpoint_url}, Key ID: {'*' * (len(access_key)-4) + access_key[-4:] if access_key else 'None'}, Region: {region_name}")
        client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name
        )
        logger.debug(f"Successfully created S3 client for endpoint {endpoint_url} with region '{region_name}'.")
        return client
    except Exception as e:
        logger.error(f"Failed to create S3 client for {endpoint_url}: {e}", exc_info=True) # Log traceback on error
        raise

# --- Routes ---

def add_chunked_upload_routes(app):
    logger = app.logger

    @app.route('/initiate-upload', methods=['POST'])
    def initiate_upload():
        logger.debug("--- /initiate-upload START ---") # DEBUG
        if not UPLOAD_ENABLED:
            logger.warning("/initiate-upload called but UPLOAD_ENABLED is False.") # DEBUG
            return jsonify({'status': 'error', 'message': 'Upload system not configured.'}), 503

        logger.info("Received /initiate-upload request")
        if not request.is_json:
            logger.warning("Request to /initiate-upload is not JSON.") # DEBUG
            return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 400

        # Get upload ID from client request if provided (though we generate a new one)
        client_provided_upload_id = request.json.get('upload_id', 'NotProvided') # DEBUG
        logger.debug(f"Client provided upload_id in request body: {client_provided_upload_id}") # DEBUG

        # Generate a unique ID for this specific upload attempt SERVER-SIDE
        upload_id = f"upload-{uuid.uuid4()}"
        logger.debug(f"Generated SERVER-SIDE upload_id: {upload_id}") # DEBUG
        s3_upload_id = None

        try:
            data = request.json
            total_size = data.get('total_size')
            filename = data.get('filename', 'pasted_blueprint.txt')

            logger.info(f"Initiating upload: ID={upload_id}, Size={total_size}, Filename={filename}")

            if total_size is None or not isinstance(total_size, int) or total_size <= 0:
                logger.warning(f"Invalid total_size received: {total_size}") # DEBUG
                return jsonify({'status': 'error', 'message': 'Valid total_size (integer > 0) is required.'}), 400

            max_size = current_app.config.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024)
            if total_size > max_size:
                max_mb = max_size // (1024 * 1024) if max_size else 'Unknown'
                logger.warning(f"Upload {upload_id} rejected. Size {total_size} > MAX_CONTENT_LENGTH {max_size}")
                return jsonify({'status': 'error', 'message': f'Upload size ({total_size} bytes) exceeds server limit of {max_mb}MB'}), 413

            s3_key = f"uploads/{upload_id}/{filename}"
            logger.debug(f"Generated S3 key: {s3_key}") # DEBUG

            # --- Initiate S3 Multipart Upload ---
            logger.debug("Attempting to get S3 client...") # DEBUG
            s3_client = get_s3_client()
            bucket_name = current_app.config['R2_BUCKET_NAME']
            if not bucket_name:
                 logger.error("R2_BUCKET_NAME is not configured!") # DEBUG
                 raise ValueError("Bucket name not configured.")
            logger.debug(f"Attempting CreateMultipartUpload for Bucket: {bucket_name}, Key: {s3_key}") # DEBUG
            try:
                multipart_upload = s3_client.create_multipart_upload(
                    Bucket=bucket_name,
                    Key=s3_key,
                    ContentType='text/plain'
                )
                s3_upload_id = multipart_upload['UploadId']
                logger.info(f"Initiated R2/S3 multipart upload for {s3_key} with UploadId: {s3_upload_id}")
            except ClientError as s3_init_e:
                logger.error(f"R2/S3 create_multipart_upload error for {upload_id}: {s3_init_e}", exc_info=True)
                return jsonify({'status': 'error', 'message': 'Server error initiating file storage.'}), 500
            # --- End S3 Initiation ---

            task_id = str(uuid.uuid4())
            logger.debug(f"Generated Task ID: {task_id}") # DEBUG

            logger.debug("Attempting to get Redis client...") # DEBUG
            redis_client = get_redis_client()
            session_data = {
                's3_key': s3_key,
                's3_upload_id': s3_upload_id,
                'task_id': task_id,
                'total_size': total_size,
                'bytes_received': 0,
                'filename': filename,
                'last_activity': time.time(),
                'completed': 'False',
                'parts': '[]'
            }
            logger.debug(f"Attempting to HSET Redis key '{upload_id}' with data: {session_data}") # DEBUG
            redis_client.hset(upload_id, mapping=session_data)
            logger.debug(f"Attempting to EXPIRE Redis key '{upload_id}' in 3600s") # DEBUG
            redis_client.expire(upload_id, 3600)
            logger.info(f"Initiated Redis session for upload {upload_id}. Task ID: {task_id}. S3 Key: {s3_key}")

            response_data = {
                'status': 'success',
                'upload_id': upload_id, # Return the SERVER-GENERATED upload_id
                'task_id': task_id
            }
            logger.debug(f"Returning success response from /initiate-upload: {response_data}") # DEBUG
            logger.debug("--- /initiate-upload END (Success) ---") # DEBUG
            return jsonify(response_data), 201

        except redis.RedisError as e:
            logger.error(f"Redis error initiating upload {upload_id}: {e}", exc_info=True)
            if s3_upload_id and 's3_client' in locals() and 'bucket_name' in locals() and 's3_key' in locals():
                try:
                    logger.warning(f"Attempting to abort S3 upload {s3_upload_id} due to Redis error.") # DEBUG
                    s3_client.abort_multipart_upload(Bucket=bucket_name, Key=s3_key, UploadId=s3_upload_id)
                    logger.info(f"Aborted S3 multipart upload {s3_upload_id} due to Redis error.")
                except ClientError as abort_e:
                    logger.error(f"Failed to abort S3 multipart upload {s3_upload_id}: {abort_e}")
            logger.debug("--- /initiate-upload END (Redis Error) ---") # DEBUG
            return jsonify({'status': 'error', 'message': 'Server error during upload initiation (Redis).'}), 500
        except Exception as e:
            logger.error(f"Error in /initiate-upload: {e}", exc_info=True)
            if s3_upload_id and 's3_client' in locals() and 'bucket_name' in locals() and 's3_key' in locals():
                try:
                    logger.warning(f"Attempting to abort S3 upload {s3_upload_id} due to general error.") # DEBUG
                    s3_client.abort_multipart_upload(Bucket=bucket_name, Key=s3_key, UploadId=s3_upload_id)
                    logger.info(f"Aborted S3 multipart upload {s3_upload_id} due to general error.")
                except ClientError as abort_e:
                    logger.error(f"Failed to abort S3 multipart upload {s3_upload_id}: {abort_e}")
            logger.debug("--- /initiate-upload END (General Error) ---") # DEBUG
            return jsonify({'status': 'error', 'message': 'Internal server error during upload initiation.'}), 500


    @app.route('/upload-chunk', methods=['POST'])
    def upload_chunk():
        logger = _get_logger()
        upload_id = request.form.get('upload_id')
        chunk_index_str = request.form.get('chunk_index', '-1') # DEBUG
        logger.debug(f"--- /upload-chunk START (UploadID: {upload_id}, ChunkIndex: {chunk_index_str}) ---") # DEBUG

        if not UPLOAD_ENABLED:
            logger.warning("/upload-chunk called but UPLOAD_ENABLED is False.") # DEBUG
            return jsonify({'status': 'error', 'message': 'Upload system not configured.'}), 503

        if not upload_id:
            logger.warning("Missing upload_id in /upload-chunk request form.") # DEBUG
            return jsonify({'status': 'error', 'message': 'Missing upload ID'}), 400

        redis_client = None
        s3_client = None

        try:
            logger.debug(f"Attempting to get Redis client for chunk upload {upload_id}...") # DEBUG
            redis_client = get_redis_client()
            logger.debug(f"Attempting HGETALL for Redis key '{upload_id}'") # DEBUG
            session_data = redis_client.hgetall(upload_id)

            if not session_data:
                logger.warning(f"Upload chunk request for invalid/expired upload ID: {upload_id}")
                logger.debug("--- /upload-chunk END (Invalid ID) ---") # DEBUG
                return jsonify({'status': 'error', 'message': 'Invalid or expired upload ID'}), 400

            logger.debug(f"Retrieved session data from Redis for {upload_id}: {session_data}") # DEBUG

            # Convert string values back where needed
            session_data['completed'] = session_data.get('completed') == 'True'
            session_data['bytes_received'] = int(session_data.get('bytes_received', 0))
            session_data['total_size'] = int(session_data.get('total_size', 0))
            try:
                session_data['parts'] = json.loads(session_data.get('parts', '[]'))
            except json.JSONDecodeError:
                logger.warning(f"Could not parse parts JSON for upload {upload_id}, resetting.")
                session_data['parts'] = []

            if session_data.get('completed'):
                logger.warning(f"Received chunk for completed upload: {upload_id}")
                logger.debug("--- /upload-chunk END (Already Completed) ---") # DEBUG
                return jsonify({'status': 'success', 'message': 'Upload already completed.', 'task_id': session_data['task_id']}), 200

            logger.debug(f"Attempting to HSET last_activity and EXPIRE for Redis key '{upload_id}'") # DEBUG
            redis_client.hset(upload_id, 'last_activity', time.time())
            redis_client.expire(upload_id, 3600)

            # --- Get chunk data ---
            chunk_index = int(chunk_index_str) # Use already retrieved string
            if chunk_index < 0:
                logger.warning(f"Invalid chunk_index received: {chunk_index}") # DEBUG
                return jsonify({'status': 'error', 'message': 'Missing chunk index'}), 400
            if 'chunk' not in request.files:
                logger.warning("No 'chunk' file found in request files.") # DEBUG
                return jsonify({'status': 'error', 'message': "No 'chunk' file found in request"}), 400

            chunk_file = request.files['chunk']
            chunk_data = chunk_file.read()
            chunk_size = len(chunk_data)
            logger.debug(f"Read chunk {chunk_index}, size: {chunk_size} bytes.") # DEBUG

            if chunk_size == 0:
                logger.warning(f"Received empty chunk {chunk_index} for upload {upload_id}")
                logger.debug("--- /upload-chunk END (Empty Chunk) ---") # DEBUG
                return jsonify({'status': 'success', 'message': f'Empty chunk {chunk_index} received'}), 200
            # --- End get chunk data ---

            # --- S3 Upload Logic ---
            s3_key = session_data['s3_key']
            s3_upload_id = session_data['s3_upload_id']
            part_number = chunk_index + 1
            bucket_name = current_app.config['R2_BUCKET_NAME']
            logger.debug(f"Attempting to get S3 client for chunk upload {upload_id}...") # DEBUG
            s3_client = get_s3_client()
            etag = None
            try:
                logger.debug(f"Attempting S3 upload_part. Bucket: {bucket_name}, Key: {s3_key}, UploadId: {s3_upload_id}, PartNumber: {part_number}") # DEBUG
                upload_response = s3_client.upload_part(
                    Bucket=bucket_name,
                    Key=s3_key,
                    UploadId=s3_upload_id,
                    PartNumber=part_number,
                    Body=chunk_data
                )
                etag = upload_response.get('ETag')
                if not etag:
                    logger.error(f"S3 upload_part for {upload_id} Part {part_number} did not return ETag.") # DEBUG
                    raise ValueError("R2/S3 upload_part did not return an ETag.")
                logger.debug(f"Uploaded part {part_number} for {upload_id} to R2/S3. ETag: {etag}")

                current_parts = session_data['parts']
                new_part_info = {'PartNumber': part_number, 'ETag': etag}
                current_parts.append(new_part_info)
                parts_json = json.dumps(current_parts)
                logger.debug(f"Attempting to HSET Redis key '{upload_id}', field 'parts' with: {parts_json}") # DEBUG
                redis_client.hset(upload_id, 'parts', parts_json)

            except ClientError as s3_e:
                logger.error(f"R2/S3 upload_part error for {upload_id} chunk {part_number}: {s3_e}", exc_info=True)
                logger.debug("--- /upload-chunk END (S3 Upload Error) ---") # DEBUG
                return jsonify({'status': 'error', 'message': 'Server error uploading file chunk to storage.'}), 500
            # --- End S3 Upload Logic ---

            new_bytes_received = session_data['bytes_received'] + chunk_size
            logger.debug(f"Attempting to HSET Redis key '{upload_id}', field 'bytes_received' with: {new_bytes_received}") # DEBUG
            redis_client.hset(upload_id, 'bytes_received', new_bytes_received)

            logger.info(f"Received chunk index {chunk_index} ({chunk_size} bytes) for {upload_id}. Total: {new_bytes_received}/{session_data['total_size']}")

            is_complete = new_bytes_received >= session_data['total_size']
            logger.debug(f"Upload {upload_id} completion check: is_complete = {is_complete}") # DEBUG

            if is_complete:
                logger.info(f"Upload {upload_id} complete based on size. Finalizing R2/S3 upload and triggering task {session_data['task_id']}")
                logger.debug(f"Attempting to HSET Redis key '{upload_id}', field 'completed' with: 'True'") # DEBUG
                redis_client.hset(upload_id, 'completed', 'True')

                # --- Finalize S3 Upload ---
                try:
                    logger.debug(f"Attempting to HGET Redis key '{upload_id}', field 'parts'") # DEBUG
                    final_parts_str = redis_client.hget(upload_id, 'parts')
                    final_parts_list = json.loads(final_parts_str or '[]')
                    if not final_parts_list:
                         logger.error(f"Cannot complete S3 upload for {upload_id}: parts list is empty in Redis.") # DEBUG
                         raise ValueError("Cannot complete S3 upload: parts list is empty.")

                    final_parts_list.sort(key=lambda x: x['PartNumber'])
                    logger.debug(f"Completing S3 upload for {upload_id} with parts: {final_parts_list}")
                    s3_client.complete_multipart_upload(
                        Bucket=bucket_name,
                        Key=s3_key,
                        UploadId=s3_upload_id,
                        MultipartUpload={'Parts': final_parts_list}
                    )
                    logger.info(f"R2/S3 multipart upload completed for {s3_key}")
                except (ClientError, ValueError, json.JSONDecodeError) as s3_complete_e:
                    logger.error(f"R2/S3 complete_multipart_upload error for {upload_id}: {s3_complete_e}", exc_info=True)
                    try:
                        logger.warning(f"Attempting to abort S3 upload {s3_upload_id} due to completion error.") # DEBUG
                        s3_client.abort_multipart_upload(Bucket=bucket_name, Key=s3_key, UploadId=s3_upload_id)
                        logger.info(f"Aborted S3 multipart upload {s3_upload_id} due to completion error.")
                    except ClientError as abort_e:
                        logger.error(f"Failed to abort S3 multipart upload {s3_upload_id} after completion error: {abort_e}")
                    logger.debug("--- /upload-chunk END (S3 Complete Error) ---") # DEBUG
                    return jsonify({'status': 'error', 'message': 'Server error finalizing file upload.'}), 500
                # --- End Finalize S3 Upload ---

                # --- Queue Celery Task ---
                if not parse_blueprint_task or not celery:
                    logger.critical(f"Celery/Task not available for final submission (Upload {upload_id})")
                    logger.debug("--- /upload-chunk END (Celery Unavailable) ---") # DEBUG
                    return jsonify({'status': 'error', 'message': 'Server error: Task system unavailable.'}), 503

                try:
                    task_kwargs = {
                        's3_bucket': bucket_name,
                        's3_key': s3_key
                    }
                    logger.info(f"Queuing task {session_data['task_id']} with kwargs: {task_kwargs}")
                    task = parse_blueprint_task.apply_async(
                        kwargs=task_kwargs,
                        task_id=session_data['task_id']
                    )
                    logger.info(f"Task {session_data['task_id']} submitted successfully for upload {upload_id}.")

                    logger.debug(f"Attempting to DELETE Redis key '{upload_id}' after task queue.") # DEBUG
                    redis_client.delete(upload_id)
                    logger.info(f"Deleted Redis session key {upload_id} after task queue.")

                    response_data = {
                        'status': 'success',
                        'message': 'All chunks received, processing started.',
                        'task_id': session_data['task_id']
                    }
                    logger.debug(f"Returning success response from /upload-chunk (complete): {response_data}") # DEBUG
                    logger.debug("--- /upload-chunk END (Complete & Queued) ---") # DEBUG
                    return jsonify(response_data), 200

                except Exception as e_queue:
                    logger.error(f"Failed to queue final task for upload {upload_id}: {e_queue}", exc_info=True)
                    logger.debug("--- /upload-chunk END (Queue Error) ---") # DEBUG
                    return jsonify({'status': 'error', 'message': 'Server error submitting final task.'}), 500
                # --- End Queue Celery Task ---

            else:
                # Chunk received, upload ongoing
                response_data = {
                    'status': 'success',
                    'message': f'Chunk {chunk_index} received'
                }
                logger.debug(f"Returning success response from /upload-chunk (ongoing): {response_data}") # DEBUG
                logger.debug("--- /upload-chunk END (Ongoing) ---") # DEBUG
                return jsonify(response_data), 200

        except redis.RedisError as e:
            logger.error(f"Redis error during chunk upload for {upload_id}: {e}", exc_info=True)
            logger.debug("--- /upload-chunk END (Redis Error) ---") # DEBUG
            return jsonify({'status': 'error', 'message': 'Server error processing upload chunk (Redis).'}), 500
        except Exception as e:
            logger.error(f"Error in /upload-chunk for {upload_id}: {e}", exc_info=True)
            logger.debug("--- /upload-chunk END (General Error) ---") # DEBUG
            return jsonify({'status': 'error', 'message': 'Internal server error during chunk upload.'}), 500