from common import response, error_response, log_event
from storage import list_history


def lambda_handler(event, context):
    try:
        items = list_history()
    except Exception as e:  # noqa: BLE001
        log_event("history_list_failed", "", error=str(e))
        return error_response(502, "", "Could not load investigation history.", str(e))
    return response(200, {"investigations": items})
