"""
微信读书 API 客户端 V2 - 基于 freestylefly/mcp-server-weread 重写
参考: https://github.com/freestylefly/mcp-server-weread

使用 CookieCloud 获取 Cookie 来访问微信读书 API
返回符合 weread2notion-pro/weread2notionpro/weread_api_v2.py 的数据格式

这是独立版本，不需要额外的 cookiecloud_client 模块
"""
import json
import os
import re
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

import requests

# API URL 常量
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOK_INFO_URL = "https://weread.qq.com/api/book/info"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO_URL = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/getProgress"
WEREAD_SHELF_SYNC_URL = "https://weread.qq.com/web/shelf/sync"
WEREAD_BEST_REVIEW_URL = "https://weread.qq.com/web/review/list/best"


class WeReadApiV2:
    """微信读书 API 客户端 V2 - 基于 mcp-server-weread 实现"""

    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.initialized = False
        self._setup_session()

    def _setup_session(self):
        """设置会话请求头"""
        self.session.headers.update({
            'Cookie': self.cookie,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'timeout': '60000'
        })

    def _ensure_initialized(self):
        """确保会话已初始化"""
        if not self.initialized:
            self.initialized = True

    def try_get_cloud_cookie(self, url: str, uuid: str, password: str) -> Optional[str]:
        """
        从 CookieCloud 获取 Cookie

        参考 mcp-server-weread 的实现逻辑：
        1. 首先尝试 "weread.qq.com" 域名
        2. 然后尝试 "weread" 域名，并过滤真正属于 weread.qq.com 的 Cookie
        3. 最后遍历所有域名查找
        """
        if url.endswith("/"):
            url = url[:-1]

        req_url = f"{url}/get/{uuid}"
        data = {"password": password}

        try:
            response = requests.post(req_url, data=data, timeout=30)

            if response.status_code == 200:
                response_data = response.json()

                if "cookie_data" in response_data:
                    domains = list(response_data["cookie_data"].keys())
                    print(f"[CookieCloud] 可用域名: {domains}")

                    # 1. 首先尝试 "weread.qq.com" 域名
                    if "weread.qq.com" in response_data["cookie_data"]:
                        print(f"[CookieCloud] 找到 weread.qq.com 域名")
                        return self._extract_cookies_from_domain(
                            response_data["cookie_data"], "weread.qq.com"
                        )

                    # 2. 然后尝试 "weread" 域名，并过滤真正属于 weread.qq.com 的 Cookie
                    if "weread" in response_data["cookie_data"]:
                        print(f"[CookieCloud] 尝试从 weread 域名提取 Cookie")
                        weread_cookies = response_data["cookie_data"]["weread"]
                        valid_cookies = [
                            c for c in weread_cookies
                            if c.get("domain") in [".weread.qq.com", "weread.qq.com"]
                        ]

                        if valid_cookies:
                            print(f"[CookieCloud] 找到 {len(valid_cookies)} 个有效的微信读书 Cookie")
                            return "; ".join([f"{c['name']}={c['value']}" for c in valid_cookies])
                        else:
                            print(f"[CookieCloud] weread 域名下的 Cookie 不属于微信读书")

                    # 3. 最后尝试遍历所有域名，寻找包含 weread.qq.com 域名的 Cookie
                    print(f"[CookieCloud] 遍历所有域名查找微信读书 Cookie")
                    for domain in domains:
                        cookies_in_domain = response_data["cookie_data"][domain]
                        if isinstance(cookies_in_domain, list):
                            weread_cookies = [
                                c for c in cookies_in_domain
                                if c.get("domain") in [".weread.qq.com", "weread.qq.com"]
                            ]

                            if weread_cookies:
                                print(f"[CookieCloud] 在 {domain} 域名下找到 {len(weread_cookies)} 个微信读书 Cookie")
                                return "; ".join([f"{c['name']}={c['value']}" for c in weread_cookies])

                    print(f"[CookieCloud] 从 Cookie Cloud 获取数据成功，但未找到微信读书 Cookie")

                else:
                    print(f"[CookieCloud] 响应中没有 cookie_data 字段")
            else:
                print(f"[CookieCloud] 响应状态码: {response.status_code}")

        except Exception as e:
            print(f"[CookieCloud] 从 Cookie Cloud 获取 Cookie 失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[CookieCloud] 响应状态: {e.response.status_code}")

        return None

    def _extract_cookies_from_domain(self, cookie_data: Dict, domain: str) -> Optional[str]:
        """
        从指定域名提取 Cookie
        """
        cookies = cookie_data.get(domain)

        if not isinstance(cookies, list) or len(cookies) == 0:
            return None

        cookie_items = []
        for cookie in cookies:
            if cookie.get("name") and cookie.get("value"):
                cookie_items.append(f"{cookie['name']}={cookie['value']}")

        if len(cookie_items) == 0:
            return None

        print(f"[CookieCloud] 提取到 {len(cookie_items)} 个 Cookie")
        return "; ".join(cookie_items)

    def get_cookie(self) -> str:
        """
        获取微信读书 Cookie

        优先级：
        1. 环境变量 WEREAD_COOKIE
        2. CookieCloud (如果配置了 CC_URL, CC_ID, CC_PASSWORD)
        """
        # 1. 检查环境变量中的直接 Cookie
        env_cookie = os.getenv("WEREAD_COOKIE")
        if env_cookie and env_cookie.strip():
            print("[Cookie] 使用环境变量中的直接 Cookie")
            return env_cookie.strip()

        # 2. 尝试环境变量中的 Cookie Cloud 配置
        env_url = os.getenv("CC_URL")
        if not env_url:
            env_url = "https://cookiecloud.malinkang.com/"
        env_id = os.getenv("CC_ID")
        env_password = os.getenv("CC_PASSWORD")

        if env_url and env_id and env_password:
            try:
                cookie = self.try_get_cloud_cookie(env_url, env_id, env_password)
                if cookie:
                    print("[Cookie] 成功从 CookieCloud 获取 Cookie")
                    return cookie
            except Exception as e:
                print(f"[Cookie] 使用 CookieCloud 获取 Cookie 失败: {e}")

        raise Exception("没有找到 cookie，请配置 WEREAD_COOKIE 或 CookieCloud")

    def handle_errcode(self, errcode: int):
        """处理错误码"""
        if errcode in [-2012, -2010]:
            print(f"[错误] 微信读书 Cookie 过期了，请重新设置")
            raise Exception("微信读书 Cookie 过期")

    def _retry(self, func, max_attempts: int = 3, wait_ms: int = 5000):
        """重试逻辑"""
        for attempt in range(1, max_attempts + 1):
            try:
                return func()
            except Exception as e:
                if hasattr(e, 'response') and e.response is not None:
                    print(f"响应状态: {e.response.status_code}")

                if attempt == max_attempts:
                    raise e

                random_wait = wait_ms + int(time.time() * 1000) % 3000
                print(f"[重试] 第 {attempt} 次尝试失败，{random_wait}ms 后重试...")
                time.sleep(random_wait / 1000)

        raise Exception("所有重试都失败了")

    def visit_homepage(self) -> bool:
        """访问主页，初始化会话"""
        try:
            headers = self.get_standard_headers()
            requests.get(WEREAD_URL, headers=headers, timeout=30)
            print("[主页] 访问主页成功")
            return True
        except Exception as e:
            print(f"[主页] 访问主页失败: {e}")
            return False

    def get_standard_headers(self) -> Dict[str, str]:
        """获取标准请求头"""
        return {
            'Cookie': self.cookie,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
            'Connection': 'keep-alive',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'sec-ch-ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'upgrade-insecure-requests': '1'
        }

    def make_api_request(self, url: str, method: str = 'get', params: Dict = None, data: Any = None) -> Any:
        """
        发送 API 请求

        参考 mcp-server-weread 的 makeApiRequest 方法
        """
        self._ensure_initialized()

        # 确保 Cookie 已设置
        if 'Cookie' not in self.session.headers:
            self.session.headers['Cookie'] = self.cookie

        # 向 GET 请求添加时间戳避免缓存
        if params is None:
            params = {}
        if method == 'get':
            params['_'] = int(time.time() * 1000)

        try:
            if method == 'get':
                response = self.session.get(url, params=params, timeout=60)
            else:
                response = self.session.post(url, json=data, params=params, timeout=60)

            # 检查错误码
            if isinstance(response.json(), dict):
                json_data = response.json()
                if 'errcode' in json_data and json_data['errcode'] != 0:
                    self.handle_errcode(json_data['errcode'])
                    raise Exception(f"API返回错误: {json_data.get('errmsg', 'Unknown error')} (code: {json_data['errcode']})")

            return response.json()
        except Exception as e:
            print(f"API请求失败 ({url}): {e}")
            raise

    def get_bookshelf(self) -> Dict[str, Any]:
        """
        获取书架数据（存在笔记的书籍）

        使用 WEREAD_NOTEBOOKS_URL 获取有笔记的书籍
        """
        def _request():
            data = self.make_api_request(WEREAD_NOTEBOOKS_URL, "get")
            return data

        return self._retry(_request)

    def get_entire_shelf(self) -> Dict[str, Any]:
        """
        获取所有书架书籍信息

        使用 WEREAD_SHELF_SYNC_URL 获取完整的书架数据
        """
        def _request():
            data = self.make_api_request(WEREAD_SHELF_SYNC_URL, "get")
            return data

        return self._retry(_request)

    def get_notebooklist(self) -> List[Dict[str, Any]]:
        """获取笔记本列表"""
        def _request():
            data = self.make_api_request(WEREAD_NOTEBOOKS_URL, "get")
            books = data.get("books", [])
            books.sort(key=lambda x: x.get("sort", 0))
            return books

        return self._retry(_request)

    def get_bookinfo(self, book_id: str) -> Dict[str, Any]:
        """获取书籍详情"""
        def _request():
            return self.make_api_request(WEREAD_BOOK_INFO_URL, "get", params={"bookId": book_id})

        return self._retry(_request)

    def get_bookmark_list(self, book_id: str) -> List[Dict[str, Any]]:
        """获取划线/笔记列表"""
        def _request():
            data = self.make_api_request(WEREAD_BOOKMARKLIST_URL, "get", params={"bookId": book_id})
            bookmarks = data.get("updated", [])
            # 确保每个划线对象格式一致
            bookmarks = [b for b in bookmarks if b.get("markText") and b.get("chapterUid")]
            return bookmarks

        return self._retry(_request)

    def get_read_info(self, book_id: str) -> Dict[str, Any]:
        """获取阅读信息"""
        def _request():
            return self.make_api_request(WEREAD_READ_INFO_URL, "get", params={"bookId": book_id})

        return self._retry(_request)

    def get_review_list(self, book_id: str) -> List[Dict[str, Any]]:
        """获取书评列表"""
        def _request():
            data = self.make_api_request(WEREAD_REVIEW_LIST_URL, "get", params={
                "bookId": book_id,
                "listType": 4,
                "maxIdx": 0,
                "count": 0,
                "listMode": 2,
                "syncKey": 0
            })
            reviews = data.get("reviews", [])
            # 转换成正确的格式
            reviews = [x.get("review", x) for x in reviews]

            # 为书评添加 chapterUid
            reviews = [
                {**x, "chapterUid": 1000000} if x.get("type") == 4 else x
                for x in reviews
            ]
            return reviews

        return self._retry(_request)

    def get_best_reviews(self, book_id: str, count: int = 10, max_idx: int = 0, synckey: int = 0) -> Dict[str, Any]:
        """获取热门书评"""
        def _request():
            return self.make_api_request(WEREAD_BEST_REVIEW_URL, "get", params={
                "bookId": book_id,
                "synckey": synckey,
                "maxIdx": max_idx,
                "count": count
            })

        return self._retry(_request)

    def get_chapter_info(self, book_id: str) -> Dict[str, Any]:
        """
        获取章节信息

        返回格式: {chapterUid_str: chapter_info}
        """
        def _request():
            try:
                # 1. 首先访问主页，确保会话有效
                self.visit_homepage()

                # 2. 获取笔记本列表，进一步初始化会话
                self.get_notebooklist()

                # 3. 添加随机延迟，模拟真实用户行为
                delay = 1000 + int(time.time() * 1000) % 2000
                time.sleep(delay / 1000)

                # 4. 从 cookie 中提取关键信息
                wr_vid = ""
                wr_skey = ""

                vid_match = re.search(r'wr_vid=([^;]+)', self.cookie)
                skey_match = re.search(r'wr_skey=([^;]+)', self.cookie)

                if vid_match:
                    wr_vid = vid_match.group(1)
                if skey_match:
                    wr_skey = skey_match.group(1)

                # 5. 请求章节信息 - 使用 session 请求以保持 Cookie
                url = WEREAD_CHAPTER_INFO_URL
                params = {"_": int(time.time() * 1000)}

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://weread.qq.com",
                    "Referer": f"https://weread.qq.com/web/reader/{book_id}",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                }

                body = json.dumps({"bookIds": [book_id]})

                # 使用 session.post 而不是 requests.post，以保持 Cookie 一致性
                response = self.session.post(url, params=params, headers=headers, data=body, timeout=60)
                data = response.json()

                # 6. 处理多种可能的响应格式
                update = None

                # 格式1: {data: [{bookId: "xxx", updated: []}]}
                if "data" in data and isinstance(data["data"], list) and len(data["data"]) == 1 and "updated" in data["data"][0]:
                    update = data["data"][0]["updated"]
                # 格式2: {updated: []}
                elif "updated" in data and isinstance(data["updated"], list):
                    update = data["updated"]
                # 格式3: [{bookId: "xxx", updated: []}]
                elif isinstance(data, list) and len(data) > 0 and "updated" in data[0]:
                    update = data[0]["updated"]
                # 格式4: 数组本身就是章节列表
                elif isinstance(data, list) and len(data) > 0 and "chapterUid" in data[0]:
                    update = data

                if update is not None:
                    # 添加点评章节
                    update.append({
                        "chapterUid": 1000000,
                        "chapterIdx": 1000000,
                        "updateTime": 1683825006,
                        "readAhead": 0,
                        "title": "点评",
                        "level": 1
                    })

                    # 确保章节uid始终以字符串形式作为键
                    result = {}
                    for curr in update:
                        chapter_uid_str = str(curr["chapterUid"])
                        result[chapter_uid_str] = curr

                    return result

                # 检查错误码，但只在严重错误时抛出异常
                errcode = data.get("errCode") or data.get("errcode", 0)
                if errcode in [-2012, -2010]:
                    # Cookie 过期，但由于其他 API 正常工作，可能只是特定接口的问题
                    # 尝试返回空结果而不是抛出异常
                    print(f"[警告] 获取章节信息时 Cookie 可能过期 (errcode: {errcode})，返回空章节列表")
                    return {}
                elif errcode != 0:
                    self.handle_errcode(errcode)
                    errmsg = data.get('errMsg') or data.get('errmsg', 'Unknown')
                    raise Exception(f"API返回错误: {errmsg} (code: {errcode})")
                else:
                    raise Exception("获取章节信息失败，返回格式不符合预期")

            except Exception as e:
                print(f"获取章节信息失败: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"状态码: {e.response.status_code}")
                raise

        return self._retry(_request)


# 便捷函数：获取实例
def get_weread_api() -> WeReadApiV2:
    """获取微信读书 API 实例"""
    return WeReadApiV2()


# 兼容 weread_api_v2.py 的接口
def get_weread_api_v2() -> WeReadApiV2:
    """获取微信读书 API V2 实例（兼容旧命名）"""
    return WeReadApiV2()


if __name__ == "__main__":
    # 测试代码
    print("微信读书 API V2 测试")
    print("=" * 50)

    api = WeReadApiV2()

    # 测试获取笔记本列表
    print("\n1. 获取笔记本列表...")
    try:
        notebooks = api.get_notebooklist()
        print(f"✓ 获取到 {len(notebooks)} 本有笔记的书籍")
        if notebooks:
            print(f"  第一本书: {notebooks[0].get('book', {}).get('title')}")
    except Exception as e:
        print(f"✗ 失败: {e}")

    # 测试获取书架
    print("\n2. 获取书架数据...")
    try:
        bookshelf = api.get_bookshelf()
        print(f"✓ 获取书架成功")
    except Exception as e:
        print(f"✗ 失败: {e}")
