"""GitHub Gist 客户端."""

from __future__ import annotations

import json

import requests

from wgmm_monitor.models import AppConfig


class GistClient:
	"""封装 Gist 读取和写入."""

	def __init__(self, config: AppConfig) -> None:
		"""保存 Gist API 配置."""
		self.config = config

	def _headers(self) -> dict[str, str]:
		"""构造 GitHub API 请求头."""
		return {
			"Authorization": f"Bearer {self.config.github_token}",
			"Accept": "application/vnd.github.v3+json",
		}

	def fetch_urls(self) -> tuple[bool, list[str], str]:
		"""读取 Gist 中的 ``urls.txt``."""
		if not self.config.gist_id or not self.config.github_token:
			error_msg = (
				"GIST_ID 未配置" if not self.config.gist_id else "GITHUB_TOKEN 未配置"
			)
			return False, [], error_msg

		url = f"{self.config.gist_base_url}/{self.config.gist_id}"
		try:
			response = requests.get(url, headers=self._headers(), timeout=30)
			response.raise_for_status()
			data = response.json()
			files = data.get("files", {})

			if "urls.txt" not in files:
				return False, [], "Gist 中未找到 urls.txt 文件"

			content = files["urls.txt"].get("content", "")
			urls = [line.strip() for line in content.splitlines() if line.strip()]
			return True, urls, ""
		except requests.exceptions.HTTPError as exc:
			status_code = exc.response.status_code if exc.response is not None else "未知"
			return False, [], f"Gist API 请求失败: HTTP {status_code}"
		except (requests.RequestException, json.JSONDecodeError) as exc:
			return False, [], f"从 Gist 获取数据失败: {exc!s}"

	def write_new_urls(self, urls: set[str]) -> tuple[bool, str]:
		"""将新增 URL 写入 ``new.txt``."""
		if not urls:
			return True, ""

		api_url = f"{self.config.gist_base_url}/{self.config.gist_id}"
		payload = {
			"files": {
				"new.txt": {
					"content": "\n".join(sorted(urls)) + "\n",
				}
			}
		}
		try:
			response = requests.patch(
				api_url,
				headers=self._headers(),
				json=payload,
				timeout=30,
			)
			response.raise_for_status()
			return True, ""
		except requests.exceptions.HTTPError as exc:
			status_code = exc.response.status_code if exc.response is not None else "未知"
			return False, f"写入 new.txt 失败: HTTP {status_code}"
		except requests.RequestException as exc:
			return False, f"写入 new.txt 请求失败: {exc!s}"
