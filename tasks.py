# tasks.py - Complete Fixed Version
import os
import uuid
import json
import time
import logging
from typing import Dict, Any
from celery_app import celery_app
from main import render_id, get_pdf_data, generate_reversed_a4_layout
from type_b_extractor import extract_type_b_data
from screenshot import process_screenshot_workflow
import redis

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Directories
INPUT_DIR = "input"
OUTPUT_DIR = "output"
A4_DIR = "a4_layouts"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(A4_DIR, exist_ok=True)

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.from_url(REDIS_URL)
    redis_client.ping()
    logger.info("✅ Redis connected in tasks.py")
except Exception as e:
    logger.warning(f"⚠️ Redis connection failed in tasks.py: {e}")
    redis_client = None

JOB_STATUS_KEY = "job_status:{job_id}"
JOB_RESULT_KEY = "job_result:{job_id}"


def update_redis_status(job_id: str, status: str, message: str = None, result: dict = None):
    """Update job status in Redis"""
    if not redis_client or not job_id:
        return

    try:
        status_key = JOB_STATUS_KEY.format(job_id=job_id)
        status_data = {
            'status': status,
            'updated_at': time.time()
        }
        if message:
            status_data['message'] = message
        if result:
            status_data['result'] = result
            result_key = JOB_RESULT_KEY.format(job_id=job_id)
            redis_client.setex(result_key, 3600, json.dumps(result))

        redis_client.setex(status_key, 3600, json.dumps(status_data))
    except Exception as e:
        logger.warning(f"Failed to update Redis status: {e}")


@celery_app.task(bind=True, name="process_pdf_task")
def process_pdf_task(self, user_id: int, file_path: str, template: str, color_mode: str, job_id: str = None) -> Dict[str, Any]:
    """Process a single PDF file and return the result"""

    # Get job_id from parameter
    if not job_id and redis_client and self.request and hasattr(self.request, 'id'):
        try:
            # O(1) hash lookup
            job_id_bytes = redis_client.hget(
                "task_to_job_map", self.request.id)
            if job_id_bytes:
                job_id = job_id_bytes.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to lookup job_id: {e}")

    try:
        logger.info(f"Processing PDF for user {user_id}: {file_path}")

        if job_id:
            update_redis_status(job_id, 'processing',
                                'Extracting data from PDF...')

        # Extract data from PDF
        id_data = get_pdf_data(file_path)
        fcn = id_data.get('fcn', '')

        # If not Type A, try Type B extraction
        if len(fcn) != 16:
            logger.info(
                f"Falling back to Type B extraction for user {user_id}")
            id_data = extract_type_b_data(file_path, "output")

        # Generate request ID
        request_id = str(uuid.uuid4())[:8]
        id_data['request_id'] = request_id

        # Prepare paths
        base_template = template.replace('_color', '').replace('_grey', '')
        template_path = f"templates/{base_template}.jpg"

        output_filename = f"ID_{user_id}_{request_id}.png"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        a4_filename = f"A4_ID_{user_id}_{request_id}.png"
        a4_path = os.path.join(A4_DIR, a4_filename)

        if job_id:
            update_redis_status(job_id, 'processing', 'Rendering ID card...')

        # Render the ID
        output_path = render_id(id_data, template_path, color_mode)

        if job_id:
            update_redis_status(job_id, 'processing',
                                'Generating A4 layout...')

        # Generate A4 layout
        a4_path = generate_reversed_a4_layout(output_path)

        # Clean up input file
        if os.path.exists(file_path):
            os.remove(file_path)

        # Include created_epoch for report error functionality
        result = {
            'success': True,
            'user_id': user_id,
            'request_id': request_id,
            'output_path': output_path,
            'a4_path': a4_path,
            'data_json': json.dumps(id_data),
            'template': template,
            'color_mode': color_mode,
            'created_epoch': time.time()
        }

        if job_id:
            update_redis_status(job_id, 'completed',
                                'Processing complete!', result)

        return result

    except Exception as e:
        logger.error(
            f"Error processing PDF for user {user_id}: {e}", exc_info=True)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

        error_result = {
            'success': False,
            'user_id': user_id,
            'error': str(e),
            'file_path': file_path
        }

        if job_id:
            update_redis_status(
                job_id, 'failed', f'Error: {str(e)[:100]}', error_result)

        return error_result


@celery_app.task(bind=True, name="process_screenshot_task")
def process_screenshot_task(self, user_id: int, front_path: str, back_path: str, template: str, color_mode: str, job_id: str = None) -> Dict[str, Any]:
    """Process screenshot images and return the result"""

    if not job_id and redis_client and self.request and hasattr(self.request, 'id'):
        try:
            job_id_bytes = redis_client.hget(
                "task_to_job_map", self.request.id)
            if job_id_bytes:
                job_id = job_id_bytes.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to lookup job_id: {e}")

    try:
        logger.info(f"Processing screenshots for user {user_id}")

        if job_id:
            update_redis_status(job_id, 'processing',
                                'Processing screenshots...')

        # Process screenshots
        base_template = template.replace('_color', '').replace('_grey', '')
        template_path = f"templates/{base_template}.jpg"

        result = process_screenshot_workflow(
            front_path, back_path, template_path, color_mode)

        # Handle different return types
        if isinstance(result, tuple) and len(result) == 3:
            id_data, output_path, a4_path = result
        else:
            id_data = result
            request_id = str(uuid.uuid4())[:8]
            id_data['request_id'] = request_id

            output_filename = f"ID_{user_id}_{request_id}.png"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            a4_filename = f"A4_ID_{user_id}_{request_id}.png"
            a4_path = os.path.join(A4_DIR, a4_filename)

            if job_id:
                update_redis_status(job_id, 'processing',
                                    'Rendering ID from screenshots...')

            output_path = render_id(id_data, template_path, color_mode)
            a4_path = generate_reversed_a4_layout(output_path)

        # Clean up input files
        for path in [front_path, back_path]:
            if os.path.exists(path):
                os.remove(path)

        request_id = id_data.get('request_id', str(uuid.uuid4())[:8])

        result = {
            'success': True,
            'user_id': user_id,
            'request_id': request_id,
            'output_path': output_path,
            'a4_path': a4_path,
            'data_json': json.dumps(id_data),
            'template': template,
            'color_mode': color_mode,
            'created_epoch': time.time()
        }

        if job_id:
            update_redis_status(job_id, 'completed',
                                'Processing complete!', result)

        return result

    except Exception as e:
        logger.error(
            f"Error processing screenshots for user {user_id}: {e}", exc_info=True)
        for path in [front_path, back_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

        error_result = {
            'success': False,
            'user_id': user_id,
            'error': str(e),
            'front_path': front_path,
            'back_path': back_path
        }

        if job_id:
            update_redis_status(
                job_id, 'failed', f'Error: {str(e)[:100]}', error_result)

        return error_result


@celery_app.task(bind=True, name="process_bulk_task")
def process_bulk_task(self, user_id: int, file_paths: list, template: str, color_mode: str, job_id: str = None) -> Dict[str, Any]:
    """Process multiple PDFs in bulk"""

    if not job_id and redis_client and self.request and hasattr(self.request, 'id'):
        try:
            job_id_bytes = redis_client.hget(
                "task_to_job_map", self.request.id)
            if job_id_bytes:
                job_id = job_id_bytes.decode('utf-8')
        except Exception as e:
            logger.warning(f"Failed to lookup job_id: {e}")

    results = []
    successful = 0
    errors = []

    logger.info(
        f"Processing bulk task for user {user_id} with {len(file_paths)} files")

    if job_id:
        update_redis_status(job_id, 'processing',
                            f'Processing {len(file_paths)} files...')

    for idx, file_path in enumerate(file_paths):
        try:
            if job_id:
                update_redis_status(
                    job_id, 'processing', f'Processing file {idx+1}/{len(file_paths)}...')

            result = process_pdf_task(
                user_id, file_path, template, color_mode, job_id=None)
            if result['success']:
                successful += 1
                results.append(result)
            else:
                errors.append(result)
        except Exception as e:
            logger.error(f"Bulk processing error for file {file_path}: {e}")
            errors.append({'file': file_path, 'error': str(e)})

    final_result = {
        'success': True,
        'user_id': user_id,
        'total': len(file_paths),
        'successful': successful,
        'errors': errors,
        'results': results,
        'created_epoch': time.time()
    }

    if job_id:
        update_redis_status(
            job_id, 'completed', f'Completed {successful}/{len(file_paths)} files', final_result)

    return final_result
