"""探测当前 API 凭证可访问的模型列表。"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI


def parse_args():
    parser = argparse.ArgumentParser(description="探测 OpenAI-compatible API 支持的模型")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL"),
        help="API 地址，默认读取 OPENAI_BASE_URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY"),
        help="API Key，默认读取 OPENAI_API_KEY",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    if not args.api_key:
        print("未找到 OPENAI_API_KEY，请在 .env 中配置或使用 --api-key。", file=sys.stderr)
        return 1

    client_options = {"api_key": args.api_key}
    if args.base_url:
        print(f"使用 API 地址：{args.base_url}")
        client_options["base_url"] = args.base_url

    try:
        client = OpenAI(**client_options)
        models = list(client.models.list().data)
    except Exception as exc:
        print(f"探测失败：{exc}", file=sys.stderr)
        return 1

    models.sort(key=lambda model: model.id)
    if args.json:
        print(json.dumps([model.model_dump() for model in models], ensure_ascii=False, indent=2))
    else:
        print(f"共发现 {len(models)} 个模型：")
        for model in models:
            owner = getattr(model, "owned_by", "")
            suffix = f" ({owner})" if owner else ""
            print(f"- {model.id}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
