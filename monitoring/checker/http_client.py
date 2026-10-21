from typing import Optional, Dict, Any
import requests


class HttpClient:

    @staticmethod
    def post(
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        response = requests.post(url, json=json_data, headers=headers, timeout=timeout,verify=False)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get(
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        response = requests.get(url, params=params, headers=headers, timeout=timeout,verify=False)
        response.raise_for_status()
        return response.json()
