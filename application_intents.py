"""Only explicit, audited non-delivery can reopen a saved application intent."""

def blocks_application(record):
    if not isinstance(record, dict) or record.get('status') != 'retry_allowed':
        return True
    evidence = record.get('reconciliation')
    return not (isinstance(evidence, dict)
                and evidence.get('result') == 'not_sent'
                and evidence.get('reason') == 'explicit_captcha_rejection_and_no_negotiation'
                and evidence.get('http_status') == 403
                and evidence.get('response_kind') == 'captcha'
                and evidence.get('negotiations_checked') == ['active', 'archived']
                and evidence.get('checked_at'))
