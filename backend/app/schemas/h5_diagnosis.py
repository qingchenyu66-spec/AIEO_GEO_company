from pydantic import BaseModel, Field, field_validator

from app.core.lead_diagnosis_prompts import normalize_lead_prompts

# 2026-09-01 - precreate=支付宝当面付扫码；mweb 留给微信 H5，暂未接
_H5_PAY_TRADE_TYPES = {"jsapi", "native", "wap", "precreate", "mweb"}
_H5_PAY_CHANNELS = {"wechat", "alipay"}


class H5DiagnosisOrderCreateRequest(BaseModel):
    contact_phone: str = Field(min_length=11, max_length=30)
    brand_name: str = Field(min_length=1, max_length=100)
    prompts: list[str] = Field(min_length=1, max_length=5)
    wechat_id: str = Field(default="", max_length=64)
    brand_aliases: str = Field(default="", max_length=500)
    industry: str = Field(default="", max_length=200)
    product_focus: str = Field(default="", max_length=200)
    website_url: str = Field(default="", max_length=500)
    competitors: str = Field(default="", max_length=500)
    # 2026-08-31 - B3：jsapi=微信内；native=PC 微信扫码
    # 2026-09-01 - alipay+wap=手机支付宝；alipay+precreate=PC 支付宝扫码
    pay_trade_type: str = Field(default="jsapi", max_length=20)
    pay_channel: str = Field(default="wechat", max_length=20)

    @field_validator("prompts")
    @classmethod
    def normalize_prompts(cls, value: list[str]) -> list[str]:
        return normalize_lead_prompts(value)

    @field_validator("brand_aliases", "competitors", mode="before")
    @classmethod
    def keep_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("pay_trade_type")
    @classmethod
    def normalize_trade_type(cls, value: object) -> str:
        text = str(value or "jsapi").strip().lower()
        if text not in _H5_PAY_TRADE_TYPES:
            raise ValueError("不支持的支付方式")
        return text

    @field_validator("pay_channel")
    @classmethod
    def normalize_channel(cls, value: object) -> str:
        text = str(value or "wechat").strip().lower() or "wechat"
        if text not in _H5_PAY_CHANNELS:
            raise ValueError("暂仅支持微信或支付宝")
        return text


class H5ResultUnlockRequest(BaseModel):
    # 2026-09-01 - 结果页无短信链时用手机号后四位换 token
    phone_tail: str = Field(min_length=4, max_length=4)

    @field_validator("phone_tail")
    @classmethod
    def digits_only(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text.isdigit() or len(text) != 4:
            raise ValueError("请填写手机号后四位")
        return text
