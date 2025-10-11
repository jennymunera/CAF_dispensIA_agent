import logging
import requests

class NotificationsService:
    def __init__(self, url_base: str):
        self.url_base = url_base
    
    def send(self, data: dict):
        try:
            logging.info(f"Notification send function inside.")
            url = f"{self.url_base}/email-notification"
            headers = {
            "Content-Type": "application/json"
            }
            response = requests.post(url, json=data, headers=headers)
            logging.info(f"Notification POST {url} -> {response.status_code}")
            if response.status_code >= 400:
                logging.warning(f"Notification failed: {response.status_code} | {response.text}")
            return response
        except Exception as e:
            logging.exception(f"[NotificationsService - send] - Error: {e}")
            raise