#!/bin/bash
# WeChat AI Bridge - Gateway 模式启动脚本
# 后台运行，关闭终端也不会中断

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/wechat_ai_bridge.log"
PID_FILE="/tmp/wechat_ai_bridge.pid"

case "$1" in
    start)
        # 检查是否已在运行
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "已在运行 (PID: $(cat $PID_FILE))"
            echo "查看日志: tail -f $LOG_FILE"
            exit 0
        fi

        echo "启动 WeChat AI Bridge (Gateway 模式)..."
        cd "$SCRIPT_DIR"
        nohup python3 -u gateway_main.py > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"

        sleep 1
        if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "启动成功 (PID: $(cat $PID_FILE))"
            echo "查看日志: tail -f $LOG_FILE"
        else
            echo "启动失败，查看日志: cat $LOG_FILE"
            exit 1
        fi
        ;;

    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 $PID 2>/dev/null; then
                echo "停止服务 (PID: $PID)..."
                kill $PID
                rm -f "$PID_FILE"
                echo "已停止"
            else
                echo "进程不存在，清理 PID 文件"
                rm -f "$PID_FILE"
            fi
        else
            echo "服务未运行"
        fi
        ;;

    restart)
        $0 stop
        sleep 1
        $0 start
        ;;

    status)
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "运行中 (PID: $(cat $PID_FILE))"
            echo "日志: $LOG_FILE"
        else
            echo "未运行"
        fi
        ;;

    log)
        tail -f "$LOG_FILE"
        ;;

    *)
        echo "WeChat AI Bridge - Gateway 模式"
        echo ""
        echo "用法: $0 {start|stop|restart|status|log}"
        echo ""
        echo "  start   - 启动服务"
        echo "  stop    - 停止服务"
        echo "  restart - 重启服务"
        echo "  status  - 查看状态"
        echo "  log     - 查看日志"
        ;;
esac
