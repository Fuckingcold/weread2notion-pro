"""
CookieCloud 客户端模块
用于从 CookieCloud 服务器获取微信读书的 Cookie
"""
import json
import hashlib
import base64
from typing import Optional, Dict

import requests


class CookieCloudClient:
    """CookieCloud 客户端"""

    def __init__(self, url: str = None, uuid: str = None, password: str = None):
        """
        初始化 CookieCloud 客户端

        Args:
            url: CookieCloud 服务器地址，默认使用官方服务器
            uuid: 用户 UUID（在 CookieCloud 中称为 ID）
            password: 密码，用于解密数据
        """
        self.url = url if url else "https://cookiecloud.malinkang.com/"
        self.uuid = uuid
        self.password = password

    def _derive_key(self, password: str) -> tuple:
        """
        从密码派生密钥（AES key 和 IV）

        Args:
            password: 密码

        Returns:
            (key, iv) 元组
        """
        # 使用 SHA256 生成 32 字节密钥
        key = hashlib.sha256(password.encode()).digest()
        # 使用密码的 MD5 生成 16 字节 IV
        iv = hashlib.md5(password.encode()).digest()
        return key, iv

    def _decrypt(self, encrypted_data: str, password: str) -> str:
        """
        解密数据（使用 AES-256-CBC）

        Args:
            encrypted_data: Base64 编码的加密数据
            password: 密码

        Returns:
            解密后的 JSON 字符串
        """
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
        except ImportError:
            # 如果没有安装 pycryptodome，使用简单的 base64 解码
            # 某些 CookieCloud 服务器可能不进行加密
            try:
                return base64.b64decode(encrypted_data).decode('utf-8')
            except:
                raise ImportError("请安装 pycryptodome: pip install pycryptodome")

        key, iv = self._derive_key(password)

        # Base64 解码
        encrypted_bytes = base64.b64decode(encrypted_data)

        # AES-256-CBC 解密
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)

        return decrypted.decode('utf-8')

    def _find_domain_key(self, domain: str, cookie_data: Dict) -> str:
        """
        在 cookie_data 中查找匹配的域名键

        支持的域名格式：
        - weread.qq.com (精确匹配)
        - .weread.qq.com (子域名通配)
        - www.weread.qq.com (完整子域名)

        Args:
            domain: 要查找的域名，如 weread.qq.com
            cookie_data: cookie 数据字典

        Returns:
            匹配的域名键，如果没有找到返回 None
        """
        # 精确匹配
        if domain in cookie_data:
            return domain

        # 尝试带点前缀的格式（如 .weread.qq.com）
        with_dot = f".{domain}"
        if with_dot in cookie_data:
            return with_dot

        # 遍历所有键，查找包含该域名的键
        for key in cookie_data.keys():
            if key == domain or key == with_dot or key.endswith(domain):
                return key

        return None

    def get_cookies(self, domain: str = None) -> Dict:
        """
        从 CookieCloud 服务器获取 Cookie

        Args:
            domain: 可选，指定域名（如 weread.qq.com）

        Returns:
            Cookie 数据字典，格式为 {domain: [cookie_list]}
        """
        if not self.uuid:
            raise ValueError("未设置 UUID")

        if self.url.endswith('/'):
            url = f"{self.url}get/{self.uuid}"
        else:
            url = f"{self.url}/get/{self.uuid}"

        try:
            response = requests.post(url, data={"password": self.password or ""})
        except requests.RequestException as e:
            raise Exception(f"连接 CookieCloud 服务器失败: {e}")

        if response.status_code != 200:
            raise Exception(f"CookieCloud 服务器返回错误状态码: {response.status_code}")

        try:
            data = response.json()
            print(f"CookieCloud 返回的数据结构: {type(data)} - {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
        except json.JSONDecodeError:
            raise Exception(f"CookieCloud 返回的不是有效的 JSON: {response.text}")

        # 获取 cookie_data 数据
        cookie_data = data.get("cookie_data")

        if not cookie_data:
            print(f"警告：没有找到 cookie_data 字段，完整数据: {data}")
            # 如果没有 cookie_data，尝试直接使用整个响应
            cookie_data = data

        # 如果 cookie_data 是字符串，尝试解析
        if isinstance(cookie_data, str):
            try:
                # 如果有密码，尝试解密
                if self.password:
                    cookie_data = self._decrypt(cookie_data, self.password)
                    if isinstance(cookie_data, str):
                        cookie_data = json.loads(cookie_data)
                else:
                    # 没有密码，尝试 base64 解码
                    cookie_data = json.loads(base64.b64decode(cookie_data).decode('utf-8'))
            except:
                try:
                    cookie_data = json.loads(cookie_data)
                except:
                    raise Exception(f"无法解析 cookie_data 数据: {cookie_data}")

        print(f"解析后的 cookie_data: {list(cookie_data.keys()) if isinstance(cookie_data, dict) else 'Not a dict'}")

        # 如果 cookie_data 不是字典，返回原始数据
        if not isinstance(cookie_data, dict):
            raise Exception(f"cookie_data 格式错误，期望 dict，实际 {type(cookie_data)}")

        # 如果指定了域名，只返回该域名的 Cookie
        if domain:
            matched_key = self._find_domain_key(domain, cookie_data)
            if matched_key:
                return {matched_key: cookie_data[matched_key]}
            raise Exception(f"CookieCloud 中没有找到 {domain} 的 Cookie，可用域名: {list(cookie_data.keys())}")

        return cookie_data

    def get_cookie_string(self, domain: str) -> str:
        """
        获取指定域名的 Cookie 字符串

        Args:
            domain: 域名，如 weread.qq.com

        Returns:
            Cookie 字符串，格式为 "key1=value1; key2=value2"
        """
        cookies_data = self.get_cookies(domain)

        # 使用 _find_domain_key 查找匹配的域名键
        matched_key = self._find_domain_key(domain, cookies_data)
        if not matched_key:
            raise Exception(f"CookieCloud 中没有找到 {domain} 的 Cookie，可用域名: {list(cookies_data.keys())}")

        cookies = cookies_data[matched_key]
        cookie_str = "; ".join(
            [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
        )

        return cookie_str

    def get_cookie_dict(self, domain: str) -> Dict[str, str]:
        """
        获取指定域名的 Cookie 字典

        Args:
            domain: 域名，如 weread.qq.com

        Returns:
            Cookie 字典，格式为 {name: value}
        """
        cookies_data = self.get_cookies(domain)

        # 使用 _find_domain_key 查找匹配的域名
        matched_key = self._find_domain_key(domain, cookies_data)
        if not matched_key:
            raise Exception(f"CookieCloud 中没有找到 {domain} 的 Cookie，可用域名: {list(cookies_data.keys())}")

        cookies = cookies_data[matched_key]
        return {cookie['name']: cookie['value'] for cookie in cookies}


def get_weread_cookie_from_cloud(
    url: str = None,
    uuid: str = None,
    password: str = None
) -> str:
    """
    便捷函数：从 CookieCloud 获取微信读书 Cookie

    Args:
        url: CookieCloud 服务器地址
        uuid: 用户 UUID
        password: 密码

    Returns:
        Cookie 字符串
    """
    client = CookieCloudClient(url=url, uuid=uuid, password=password)
    return client.get_cookie_string("weread.qq.com")
