def build_email_payload(notification_type: str, process_name: str, sharepoint_folder: str) -> dict:
    return {
        "idProject": "CARTERA_CAF_ANALYSIS",
        "typeNotification": "EMIAL",  
        "notification": notification_type,
        "data": [
            {"label": "{{processName}}", "value": process_name},
            {"label": "{{id}}", "value": f"{sharepoint_folder}|{process_name}"}
        ]
    }