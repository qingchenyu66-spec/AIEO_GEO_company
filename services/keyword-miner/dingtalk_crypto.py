#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉回调加解密（标准协议）
========================
用于「群机器人 / 机器人」的 HTTP 回调模式：
- 验签：msg_signature = SHA1(排序拼接 token, timestamp, nonce, encrypt)
- 解密：AES-256-CBC，key = Base64Decode(EncodingAESKey + "=")，iv = key[:16]
- 明文结构：random(16B) + msg_len(4B 大端) + msg + receiveId
详见钉钉开放平台「事件订阅 / 机器人接收消息」文档。
"""
import os
import base64
import hashlib
import struct
from Crypto.Cipher import AES


class DingTalkCrypto:
    def __init__(self, token, encoding_aes_key):
        self.token = token
        # EncodingAESKey 为 43 位，补 '=' 后 Base64 解码得到 32 字节
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.aes_key[:16]

    def signature(self, timestamp, nonce, encrypt):
        arr = sorted([self.token, str(timestamp), str(nonce), encrypt])
        sha = hashlib.sha1()
        sha.update("".join(arr).encode("utf-8"))
        return sha.hexdigest()

    def verify(self, msg_signature, timestamp, nonce, encrypt):
        return self.signature(timestamp, nonce, encrypt) == msg_signature

    @staticmethod
    def _pad(text):
        block = 32  # 钉钉使用 32 字节块
        pad = block - (len(text) % block)
        return text + bytes([pad]) * pad

    @staticmethod
    def _unpad(text):
        return text[:- text[-1]] if text else text

    def decrypt(self, encrypt):
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        plain = cipher.decrypt(base64.b64decode(encrypt))
        plain = self._unpad(plain)
        msg_len = struct.unpack(">I", plain[16:20])[0]
        return plain[20:20 + msg_len].decode("utf-8")

    def encrypt(self, msg, receive_id):
        rand = os.urandom(16)
        bmsg = msg.encode("utf-8")
        length = struct.pack(">I", len(bmsg))
        text = self._pad(rand + length + bmsg + receive_id.encode("utf-8"))
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        return base64.b64encode(cipher.encrypt(text)).decode("utf-8")
