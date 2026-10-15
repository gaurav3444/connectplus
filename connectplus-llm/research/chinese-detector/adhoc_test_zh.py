"""
Ad-hoc sanity check: 40 hand-written Chinese statements, never seen by
training (not sourced from TVsub or CLUE). Mixes formal, colloquial, very
short, longer, digital-literacy/scam-domain (the actual product use case),
and two Traditional-script sentences as a stretch test -- the model only
ever trained on Simplified.
"""

from __future__ import annotations

import sys

from chinese_detector import classify

sys.stdout.reconfigure(encoding="utf-8")

STATEMENTS = [
    "我收到一条奇怪的短信，说我的银行账户被冻结了",
    "怎么把手机上的字体调大一点",
    "我不知道这个网站是不是安全的",
    "我妈妈昨天在网上买东西被骗了",
    "请问myGov账户密码忘记了怎么办",
    "这是不是诈骗电话",
    "我想学习怎么用微信视频通话",
    "谢谢你的帮助",
    "今天天气真好",
    "我孙子教我用平板电脑",
    "这个二维码可以扫吗",
    "我需要联系人工客服",
    "银行不会用短信要求你提供密码",
    "我不确定要不要点这个链接",
    "如何设置双重验证",
    "我的电子邮箱被盗了怎么办",
    "社区中心有没有电脑课程",
    "我女儿住在悉尼",
    "这个应用程序看起来很奇怪",
    "我想跟一个真人说话，不是机器人",
    "他昨天打电话给我说中了大奖",
    "我一直收不到验证码",
    "请帮我看看这封邮件是不是真的",
    "早上好",
    "我需要重新设置我的路由器",
    "这个软件更新是必要的吗",
    "我的密码太复杂了记不住",
    "退休金什么时候发放",
    "我想取消这个订阅服务",
    "警察局的电话号码是多少",
    "我在网上填了这个表格，安全吗",
    "老年人如何防止网络诈骗",
    "我的孩子帮我设置了这个手机",
    "请问图书馆几点开门",
    "这条链接看起来像钓鱼网站",
    "我不想给陌生人转账",
    "我忘记怎么打开这个相机应用了",
    "多谢，我明白了",
    "我聽不懂這個訊息在說什麼",
    "銀行絕對不會用簡訊要求密碼",
]


def main() -> None:
    n = len(STATEMENTS)
    correct = 0
    print(f"Testing {n} hand-written Chinese statements (not from TVsub/CLUE)\n")
    print(f"{'lang':<6} {'conf':<7} text")
    print("-" * 70)
    for text in STATEMENTS:
        result = classify(text)
        ok = result.lang == "zh"
        correct += ok
        mark = "  " if ok else "X "
        print(f"{mark}{result.lang:<4} {result.confidence:<7.1%} {text}")

    print(f"\n{correct}/{n} = {correct / n:.1%} correctly identified as Chinese")


if __name__ == "__main__":
    main()
