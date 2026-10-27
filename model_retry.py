"""Bounded generation retries. This module never performs Telegram actions."""
import re
import time
import requests
from autonomous_runtime import NeedsDecision


def failure(response):
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get('error', {}) if isinstance(body, dict) else {}
    if isinstance(error, str):
        error = {'code': error}
    if not isinstance(error, dict):
        error = {}
    raw_code = error.get('code', 'http_error')
    code = raw_code if isinstance(raw_code, str) and re.fullmatch(r'[a-zA-Z0-9_]{1,100}', raw_code) else 'adapter_error'
    upstream = error.get('status', response.status_code)
    if upstream == 429 or any(s in code for s in ('limit', 'quota', 'rate_exceeded')):
        return code, False, 'Достигнут лимит Luna; проверь лимиты подключения'
    if upstream in (401, 403) or any(s in code for s in ('token', 'grant', 'authoriz', 'access_denied', 'invalid_client', 'not_verified', 'not_eligible', 'invalid_user')):
        return code, False, 'Подключение Luna требует проверки входа и разрешений'
    if error:
        retry = error.get('retryable') is True
    else:
        retry = response.status_code in (408, 500, 502, 503, 504)
    return code, retry, 'Luna временно недоступна' if retry else 'Luna отклонила запрос; проверь подключение и журнал'


def generate(session, url, payload, *, timeout, config, deadline, report, logger):
    attempts = config['model_retry_attempts']
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.time() if deadline is not None else timeout
        if remaining <= 0:
            raise NeedsDecision('Время запуска истекло во время ожидания Luna; ответ не отправлен')
        report('running', phase='generating', message=f'Luna готовит ответ: попытка {attempt}/{attempts}', next_retry_at=None)
        try:
            response = session.post(url, json=payload, timeout=min(timeout, remaining))
            if response.ok:
                try:
                    content = response.json()['message']['content']
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError('empty content')
                except (ValueError, KeyError, TypeError):
                    code, retry, reason = 'invalid_response', True, 'Luna вернула неполный ответ'
                else:
                    logger.info('MODEL_TIMING: %.2fs; attempts=%d', time.monotonic()-started, attempt)
                    return content.strip()
            else:
                code, retry, reason = failure(response)
        except (requests.ConnectionError, requests.Timeout) as exc:
            code = 'timeout' if isinstance(exc, requests.Timeout) else 'connection_error'
            retry, reason = True, 'Не удалось связаться с Luna'
        logger.warning('MODEL_FAILURE: attempt=%d/%d code=%s retryable=%s', attempt, attempts, code, retry)
        if not retry or attempt == attempts:
            message = f'{reason}; код {code}. ' + ('Повторные попытки исчерпаны. ' if retry else '') + 'Ответ не отправлен; память интервью сохранена'
            report('needs_attention', phase='model_error', message=message, next_retry_at=None)
            raise NeedsDecision(message)
        delay = min(config['model_retry_initial_seconds'] * 2 ** (attempt - 1), config['model_retry_max_seconds'])
        if deadline is not None and time.time() + delay >= deadline:
            raise NeedsDecision('Время запуска истекает; повтор Luna отменён, ответ не отправлен')
        logger.info('MODEL_RETRY: in=%.1fs next_attempt=%d/%d', delay, attempt+1, attempts)
        report('running', phase='model_retry', message=f'{reason}; повтор {attempt+1}/{attempts} через {delay:g} сек.', next_retry_at=time.time()+delay)
        # Short chunks keep stop signals responsive even with a longer configured delay.
        end = time.monotonic() + delay
        while time.monotonic() < end:
            time.sleep(max(0, min(1, end-time.monotonic())))
