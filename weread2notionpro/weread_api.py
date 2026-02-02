import hashlib
import json
import os
import re

import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from urllib.parse import quote
from dotenv import load_dotenv

from .cookiecloud_client import CookieCloudClient

load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://i.weread.qq.com/user/notebooks"
WEREAD_BOOKMARKLIST_URL = "https://i.weread.qq.com/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://i.weread.qq.com/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://i.weread.qq.com/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://i.weread.qq.com/review/list"
WEREAD_BOOK_INFO = "https://i.weread.qq.com/book/info"
WEREAD_READDATA_DETAIL = "https://i.weread.qq.com/readdata/detail"
WEREAD_HISTORY_URL = "https://i.weread.qq.com/readdata/summary?synckey=0"


class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()

    def get_cookie_from_cloud(self, url, uuid, password):
        """
        从 CookieCloud 服务器获取微信读书 Cookie

        Args:
            url: CookieCloud 服务器地址
            uuid: 用户 UUID (CC_ID)
            password: 密码 (CC_PASSWORD)

        Returns:
            Cookie 字符串
        """
        try:
            print(f"正在从 CookieCloud 获取 Cookie...")
            print(f"服务器: {url}")
            print(f"UUID: {uuid[:10] if uuid else None}")

            client = CookieCloudClient(url=url, uuid=uuid, password=password)
            return client.get_cookie_string("weread.qq.com")
        except Exception as e:
            print(f"从 CookieCloud 获取 Cookie 失败: {e}")
            raise Exception(f"从 CookieCloud 获取 Cookie 失败: {e}")

    def get_cookie(self):
        """
        获取微信读书 Cookie

        优先级：
        1. CookieCloud (如果配置了 CC_URL, CC_ID, CC_PASSWORD)
        2. 环境变量 WEREAD_COOKIE
        """
        url = os.getenv("CC_URL")
        if not url:
            url = "https://cookiecloud.malinkang.com/"
        uuid = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")

        # 优先使用 CookieCloud
        if url and uuid and password:
            try:
                cookie = self.get_cookie_from_cloud(url, uuid, password)
                print("已从 CookieCloud 获取 Cookie")
            except Exception as e:
                print(f"从 CookieCloud 获取 Cookie 失败，尝试使用环境变量: {e}")
                if not cookie or not cookie.strip():
                    raise Exception("CookieCloud 获取失败且没有设置 WEREAD_COOKIE 环境变量")

        if not cookie or not cookie.strip():
            raise Exception("没有找到 cookie，请配置 CookieCloud (CC_URL, CC_ID, CC_PASSWORD) 或 WEREAD_COOKIE 环境变量")
        return cookie

    def parse_cookie_string(self):
        """
        解析 Cookie 字符串为 cookiejar

        修复原问题：原代码使用 unicode_escape 会破坏 URL 编码的 cookie 值
        现在直接使用原始值，保持 URL 编码格式
        """
        cookies_dict = {}

        # 使用正则表达式解析 cookie 字符串
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)

        for key, value in matches:
            # 直接使用原始值，不进行 unicode_escape 编码
            # 保持 URL 编码格式（如 %2C, %7B 等）
            cookies_dict[key] = value

        # 直接使用 cookies_dict 创建 cookiejar
        cookiejar = cookiejar_from_dict(cookies_dict)

        return cookiejar

    def get_bookshelf(self):
        self.session.get(WEREAD_URL)
        r = self.session.get(
            "https://i.weread.qq.com/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0"
        )
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode",0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get bookshelf {r.text}")

    def handle_errcode(self, errcode):
        if errcode == -2012 or errcode == -2010:
            print(f"::error::微信读书Cookie过期了，请参考文档重新设置。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_notebooklist(self):
        """获取笔记本列表"""
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_NOTEBOOKS_URL)
        if r.ok:
            data = r.json()
            books = data.get("books")
            books.sort(key=lambda x: x["sort"])
            return books
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get notebook list {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookinfo(self, bookId):
        """获取书的详情"""
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOK_INFO, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            print(f"Could not get book info {r.text}")


    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookmark_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOKMARKLIST_URL, params=params)
        if r.ok:
            # 调试时可以写入文件，但在 CI/CD 环境中可能导致问题
            # with open("bookmark.json","w") as f:
            #     f.write(json.dumps(r.json(),indent=4,ensure_ascii=False))
            bookmarks = r.json().get("updated")
            return bookmarks
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"Could not get {bookId} bookmark list")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_read_info(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(
            noteCount=1,
            readingDetail=1,
            finishedBookIndex=1,
            readingBookCount=1,
            readingBookIndex=1,
            finishedBookCount=1,
            bookId=bookId,
            finishedDate=1,
        )
        headers = {
            "baseapi":"32",
            "appver":"8.2.5.10163885",
            "basever":"8.2.5.10163885",
            "osver":"12",
            "User-Agent": "WeRead/8.2.5 WRBrand/xiaomi Dalvik/2.1.0 (Linux; U; Android 12; Redmi Note 7 Pro Build/SQ3A.220705.004)",
        }
        r = self.session.get(WEREAD_READ_INFO_URL, headers=headers, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"get {bookId} read info failed {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_review_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
        r = self.session.get(WEREAD_REVIEW_LIST_URL, params=params)
        if r.ok:
            reviews = r.json().get("reviews")
            reviews = list(map(lambda x: x.get("review"), reviews))
            reviews = [
                {"chapterUid": 1000000, **x} if x.get("type") == 4 else x
                for x in reviews
            ]
            return reviews
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"get {bookId} review list failed {r.text}")



    def get_api_data(self):
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_HISTORY_URL)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"get history data failed {r.text}")


    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_chapter_info(self, bookId):
        self.session.get(WEREAD_URL)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body)
        if (
            r.ok
            and "data" in r.json()
            and len(r.json()["data"]) == 1
            and "updated" in r.json()["data"][0]
        ):
            update = r.json()["data"][0]["updated"]
            update.append(
                {
                    "chapterUid": 1000000,
                    "chapterIdx": 1000000,
                    "updateTime": 1683825006,
                    "readAhead": 0,
                    "title": "点评",
                    "level": 1,
                }
            )
            return {item["chapterUid"]: item for item in update}
        else:
            raise Exception(f"get {bookId} chapter info failed {r.text}")

    def transform_id(self, book_id):
        id_length = len(book_id)
        if re.match("^\\d*$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i : min(i + 9, id_length)]), "x"))
            return "3", ary

        result = ""
        for i in range(id_length):
            result += format(ord(book_id[i]), "x")
        return "4", [result]

    def calculate_book_str_id(self, book_id):
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self.transform_id(book_id)
        result += code + "2" + digest[-2:]

        for i in range(len(transformed_ids)):
            hex_length_str = format(len(transformed_ids[i]), "x")
            if len(hex_length_str) == 1:
                hex_length_str = "0" + hex_length_str

            result += hex_length_str + transformed_ids[i]

            if i < len(transformed_ids) - 1:
                result += "g"

        if len(result) < 20:
            result += digest[0 : 20 - len(result)]

        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[0:3]
        return result

    def get_url(self, book_id):
        return f"https://weread.qq.com/web/reader/{self.calculate_book_str_id(book_id)}"
