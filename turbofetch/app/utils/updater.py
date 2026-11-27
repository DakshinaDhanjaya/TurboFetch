from typing import Tuple

import httpx


class UpdateChecker:
    GITHUB_REPO: str = "DakshinaDhanjaya/TurboFetch"
    CURRENT_VERSION: str = "1.0.0"
    API_URL: str = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    @staticmethod
    def _parse_version(version: str) -> Tuple[int, ...]:
        cleaned = version.lstrip("vV")
        parts = cleaned.split("-")[0].split(".")
        parsed = []
        for p in parts:
            digits = "".join(ch for ch in p if ch.isdigit())
            parsed.append(int(digits) if digits else 0)
        return tuple(parsed)

    @classmethod
    def _is_newer(cls, latest: str, current: str) -> bool:
        return cls._parse_version(latest) > cls._parse_version(current)

    async def check_for_updates(
        self, timeout: float = 15.0
    ) -> Tuple[bool, str, str]:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                headers = {"Accept": "application/vnd.github.v3+json"}
                response = await client.get(self.API_URL, headers=headers)
                if response.status_code != 200:
                    return False, self.CURRENT_VERSION, ""
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return False, self.CURRENT_VERSION, ""

        tag_name: str = data.get("tag_name", "")
        if not tag_name:
            return False, self.CURRENT_VERSION, ""

        download_url = self._extract_download_url(data)
        has_update = self._is_newer(tag_name, self.CURRENT_VERSION)
        return has_update, tag_name.lstrip("vV"), download_url

    @staticmethod
    def _extract_download_url(release_data: dict) -> str:
        assets: list = release_data.get("assets", [])
        if assets:
            return assets[0].get("browser_download_url", "")
        return release_data.get("html_url", "")
