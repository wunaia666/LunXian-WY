"""在已有本机识字环境中读取正常渲染的小说页面，不解密网页字体。"""

import json
import sys


def main():
    from rapidocr_onnxruntime import RapidOCR

    paths = json.load(sys.stdin)
    if not isinstance(paths, list) or not 1 <= len(paths) <= 4:
        raise ValueError("每次只能识别一至四页")
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    pages = []
    for path in paths:
        rows, _ = engine(path)
        lines = [text for _, text, score in rows or [] if score >= 0.65]
        pages.append("\n".join(lines))
    print(json.dumps({"pages": pages}, ensure_ascii=False))


if __name__ == "__main__":
    main()
