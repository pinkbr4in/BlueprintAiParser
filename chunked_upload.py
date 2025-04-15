import os
import time
import tempfile
import random
import uuid
import logging
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

# WARNING: In-memory storage - not suitable for production with multiple workers! Use Redis/DB.
upload_sessions = {}
# ------------------------------------------------------------------------------------

# Simple time-based cleanup (Rudimentary)
_last_cleanup_time = 0
CLEANUP_INTERVAL = 300  # Seconds (5 minutes)
SESSION_TIMEOUT = 3600  # Seconds (1 hour)

def _get_logger():
    # Helper to get logger safely, works during requests or startup
    try:
        return current_app.logger
    except RuntimeError:  # Outside of application context
        return logging.getLogger('chunked_upload')

def _cleanup_old_sessions(force=False):
    """Remove temporary files and session info for old/completed uploads."""
    global _last_cleanup_time
    now = time.time()
    logger = _get_logger()

    if not force and (now - _last_cleanup_time) < CLEANUP_INTERVAL:
        return

    logger.info("Running upload session cleanup...")
    sessions_to_remove = []
    # Iterate over a copy of items for safe deletion
    for upload_id, session_data in list(upload_sessions.items()):
        last_activity = session_data.get('last_activity', 0)
        is_timed_out = (now - last_activity) > SESSION_TIMEOUT
        # Don't remove 'completed' here, only timed out or explicitly cleared
        if is_timed_out:
            file_path = session_data.get('file_path')
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                    logger.info(f"Cleaned up timed-out temp file: {file_path} for upload {upload_id}")
                except Exception as e:
                    logger.error(f"Error cleaning up timed-out file {file_path} for upload {upload_id}: {e}")
            else:
                 logger.warning(f"Temp file {file_path} not found for timed-out session {upload_id}.")
            sessions_to_remove.append(upload_id)

    removed_count = 0
    for upload_id in sessions_to_remove:
        if upload_id in upload_sessions:
            del upload_sessions[upload_id]
            removed_count += 1

    _last_cleanup_time = now
    if removed_count > 0:
        logger.info(f"Cleanup finished. Removed {removed_count} timed-out sessions.")


def add_chunked_upload_routes(app):
    """Add routes to handle chunked file uploads to the Flask app."""
    logger = app.logger
    
    # Get app's CSRF instance if it exists
    csrf = app.extensions.get('csrf', None)
    
    @app.before_request
    def before_request_cleanup_hook():
        _cleanup_old_sessions()  # Run cleanup occasionally

    # Route to initiate upload, reserve task ID, create temp file
    @app.route('/initiate-upload', methods=['POST'])
    def initiate_upload():
        if not UPLOAD_ENABLED:
            return jsonify({'status': 'error', 'message': 'Upload system not configured.'}), 503

        logger.info("Received /initiate-upload request")
        if not request.is_json:
            return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 400

        try:
            data = request.json
            upload_id = data.get('upload_id', str(uuid.uuid4()))
            total_size = data.get('total_size')
            filename = data.get('filename', 'pasted_blueprint.txt')

            logger.info(f"Initiating upload: ID={upload_id}, Size={total_size}, Filename={filename}")

            if total_size is None or not isinstance(total_size, int) or total_size <= 0:
                return jsonify({'status': 'error', 'message': 'Valid total_size (integer) is required.'}), 400

            max_size = current_app.config.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024)
            if total_size > max_size:
                max_mb = max_size // (1024 * 1024) if max_size else 'Unknown'
                return jsonify({'status': 'error', 'message': f'Upload size ({total_size} bytes) exceeds limit of {max_mb}MB'}), 413

            # Clean up potentially stale session with the same ID
            if upload_id in upload_sessions:
                 logger.warning(f"Upload ID {upload_id} collision. Cleaning up old session.")
                 _cleanup_old_sessions(force=True)

            # Create temporary file
            upload_folder = current_app.config.get('UPLOAD_FOLDER', tempfile.gettempdir())
            if not os.path.exists(upload_folder): os.makedirs(upload_folder, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(suffix='.txt', prefix=f'bp_upload_{upload_id}_', dir=upload_folder)
            os.close(fd)  # Close descriptor, we'll append in binary mode

            # Reserve Task ID
            task_id = str(uuid.uuid4())

            # Store session
            upload_sessions[upload_id] = {
                'file_path': temp_path,
                'task_id': task_id,
                'total_size': total_size,
                'bytes_received': 0,
                'filename': filename,
                'last_activity': time.time(),
                'completed': False
            }

            logger.info(f"Initiated upload {upload_id}. Task ID: {task_id}. Temp file: {temp_path}")
            return jsonify({
                'status': 'success',
                'upload_id': upload_id,
                'task_id': task_id
            }), 201

        except Exception as e:
            logger.error(f"Error in /initiate-upload: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': 'Internal server error during upload initiation.'}), 500

    # Route to upload individual chunks
    @app.route('/upload-chunk', methods=['POST'])
    def upload_chunk():
        if not UPLOAD_ENABLED:
            return jsonify({'status': 'error', 'message': 'Upload system not configured.'}), 503

        logger = current_app.logger
        upload_id = request.form.get('upload_id')

        if not upload_id or upload_id not in upload_sessions:
            return jsonify({'status': 'error', 'message': 'Invalid or missing upload ID'}), 400

        session_data = upload_sessions[upload_id]

        if session_data.get('completed'):
             logger.warning(f"Received chunk for completed upload: {upload_id}")
             return jsonify({'status': 'success', 'message': 'Upload already completed.', 'task_id': session_data['task_id']}), 200

        if (time.time() - session_data.get('last_activity', 0)) > SESSION_TIMEOUT:
             logger.error(f"Chunk received for timed-out session: {upload_id}")
             _cleanup_old_sessions(force=True)
             return jsonify({'status': 'error', 'message': 'Upload session timed out.'}), 410

        session_data['last_activity'] = time.time()

        try:
            chunk_index = int(request.form.get('chunk_index', -1))

            if chunk_index < 0:
                return jsonify({'status': 'error', 'message': 'Missing chunk index'}), 400

            if 'chunk' not in request.files:
                return jsonify({'status': 'error', 'message': "No 'chunk' file found in request"}), 400

            chunk_file = request.files['chunk']
            chunk_size = 0
            file_path = session_data['file_path']

            # Append chunk to file
            try:
                with open(file_path, 'ab') as f:  # Append in binary mode
                    chunk_data = chunk_file.read()
                    chunk_size = len(chunk_data)
                    if chunk_size == 0:
                        logger.warning(f"Received empty chunk {chunk_index} for upload {upload_id}")
                        return jsonify({'status': 'success', 'message': f'Empty chunk {chunk_index} received'}), 200

                    f.write(chunk_data)
            except IOError as e:
                 logger.error(f"IOError writing chunk for {upload_id} to {file_path}: {e}", exc_info=True)
                 return jsonify({'status': 'error', 'message': 'Server error writing file chunk.'}), 500

            session_data['bytes_received'] += chunk_size
            logger.info(f"Received chunk index {chunk_index} ({chunk_size} bytes) for {upload_id}. Total: {session_data['bytes_received']}/{session_data['total_size']}")

            # Check if complete based on total size
            is_complete = session_data['bytes_received'] >= session_data['total_size']

            if is_complete:
                logger.info(f"Upload {upload_id} complete. Final size: {session_data['bytes_received']}. Triggering task {session_data['task_id']}")
                session_data['completed'] = True  # Mark completed BEFORE queueing

                # Read the completed file
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        blueprint_raw_text = f.read()
                    logger.info(f"Read {len(blueprint_raw_text)} chars from temp file {file_path}")
                except Exception as e:
                    logger.error(f"Error reading completed file {file_path} for task {session_data['task_id']}: {e}", exc_info=True)
                    # Clean up session and file even if reading fails
                    _cleanup_old_sessions(force=True)  # Force cleanup for this ID
                    return jsonify({'status': 'error', 'message': 'Failed to read assembled file.'}), 500

                # Queue the Celery task using the reserved task ID
                if not parse_blueprint_task or not celery:
                    logger.critical(f"Celery/Task not available for final submission (Upload {upload_id})")
                    return jsonify({'status': 'error', 'message': 'Server error: Task system unavailable.'}), 503

                try:
                    task = parse_blueprint_task.apply_async(
                        kwargs={'blueprint_raw_text': blueprint_raw_text},
                        task_id=session_data['task_id']  # Use the pre-generated ID
                    )
                    logger.info(f"Task {session_data['task_id']} submitted successfully for upload {upload_id}.")

                    # Clean up temp file AFTER successful queuing
                    try:
                         if os.path.exists(file_path):
                             os.unlink(file_path)
                             logger.info(f"Deleted temp file {file_path} after task queue.")
                    except Exception as e:
                         logger.error(f"Failed to delete temp file {file_path} after queueing: {e}")

                    return jsonify({
                        'status': 'success',
                        'message': 'All chunks received, processing started.',
                        'task_id': session_data['task_id']
                    }), 200

                except Exception as e_queue:
                    logger.error(f"Failed to queue final task for upload {upload_id}: {e_queue}", exc_info=True)
                    return jsonify({'status': 'error', 'message': 'Server error submitting final task.'}), 500

            else:
                # Return success for the chunk, indicating upload is ongoing
                return jsonify({
                    'status': 'success',
                    'message': f'Chunk {chunk_index} received'
                }), 200

        except Exception as e:
            logger.error(f"Error in /upload-chunk for {upload_id}: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': 'Internal server error during chunk upload.'}), 500