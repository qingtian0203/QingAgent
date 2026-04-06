"""
QingAgent 启动入口

三种运行模式：
1. python main.py serve   — 启动 Web 服务（浏览器/手机访问）
2. python main.py cli     — 命令行交互模式
3. python main.py test    — 快速测试单条指令
"""
import sys

from qingagent.skills import SkillRegistry
from qingagent.planner.planner import Planner


def run_cli():
    """命令行交互模式"""
    print("\n🤖 QingAgent 命令行模式")
    print("输入自然语言指令，输入 'quit' 退出\n")

    registry = SkillRegistry()
    registry.auto_register()
    planner = Planner(registry)

    while True:
        try:
            user_input = input("\n晴帅 > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("👋 再见晴帅！")
                break

            # 特殊命令
            if user_input == "/skills":
                print(planner.registry.get_full_capability_description())
                continue

            planner.execute(user_input)

        except KeyboardInterrupt:
            print("\n👋 再见晴帅！")
            break


def run_server():
    """Web 服务模式"""
    from qingagent.server.app import start_server
    start_server()


def run_test(command: str):
    """快速测试单条指令"""
    registry = SkillRegistry()
    registry.auto_register()
    planner = Planner(registry)
    result = planner.execute(command)
    print(f"\n📊 最终结果：{result}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py serve          — 启动 Web 服务")
        print("  python main.py cli            — 命令行交互模式")
        print("  python main.py test '指令'    — 测试单条指令")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "serve":
        run_server()
    elif mode == "cli":
        run_cli()
    elif mode == "test":
        if len(sys.argv) < 3:
            print("❌ 请提供测试指令，如: python main.py test '给晴天发条微信'")
            sys.exit(1)
        run_test(sys.argv[2])
    else:
        print(f"❌ 未知模式：{mode}，可选: serve / cli / test")
