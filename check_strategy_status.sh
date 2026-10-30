#!/bin/bash

# Strategy Monitoring Script
# 监控策略是否正常运行，检查关键日志

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/logs/trader.log"
LATEST_LOG=$(ls -t "$REPO_DIR"/logs/trader_*.log 2>/dev/null | head -1)

echo "=========================================="
echo "策略运行状态监控"
echo "时间: $(date)"
echo "=========================================="
echo ""

# 检查进程
echo "📊 进程状态:"
ps aux | grep -E "main_live.py|python.*main_live" | grep -v grep || echo "  ❌ 未找到运行中的进程"
echo ""

# 检查最新日志文件
if [ -n "$LATEST_LOG" ]; then
    echo "📄 最新日志文件: $LATEST_LOG"
    echo ""
    
    # 检查策略初始化
    echo "🔍 策略初始化检查:"
    if grep -q "DeepSeek AI Strategy initialized" "$LATEST_LOG"; then
        echo "  ✅ 策略已初始化"
    else
        echo "  ❌ 策略未初始化"
    fi
    
    # 检查策略启动
    echo "🚀 策略启动检查:"
    if grep -q "Starting DeepSeek AI Strategy" "$LATEST_LOG"; then
        echo "  ✅ 策略已启动"
        grep "Starting DeepSeek AI Strategy" "$LATEST_LOG" | tail -1
    else
        echo "  ⚠️  策略启动日志未找到（可能正在启动中）"
    fi
    
    # 检查数据订阅
    echo "📡 数据订阅检查:"
    if grep -q "Subscribed to" "$LATEST_LOG"; then
        echo "  ✅ 已订阅数据"
        grep "Subscribed to" "$LATEST_LOG" | tail -1
    else
        echo "  ⚠️  数据订阅日志未找到"
    fi
    
    # 检查Bar数据接收
    echo "📊 Bar数据接收检查:"
    BAR_COUNT=$(grep -c "Bar #" "$LATEST_LOG" 2>/dev/null || echo "0")
    if [ "$BAR_COUNT" -gt 0 ]; then
        echo "  ✅ 已接收 $BAR_COUNT 个Bar数据"
        echo "  最新Bar数据:"
        grep "Bar #" "$LATEST_LOG" | tail -1
    else
        echo "  ⚠️  尚未接收到Bar数据"
    fi
    
    # 检查定期分析
    echo "🤖 AI分析检查:"
    if grep -q "Running periodic analysis" "$LATEST_LOG"; then
        echo "  ✅ 已执行定期分析"
        ANALYSIS_COUNT=$(grep -c "Running periodic analysis" "$LATEST_LOG")
        echo "  分析次数: $ANALYSIS_COUNT"
        echo "  最新分析:"
        grep "Running periodic analysis" "$LATEST_LOG" | tail -1
    else
        echo "  ⚠️  尚未执行定期分析"
    fi
    
    # 检查交易信号
    echo "📈 交易信号检查:"
    if grep -q "Signal:" "$LATEST_LOG"; then
        echo "  ✅ 已生成交易信号"
        echo "  最新信号:"
        grep "Signal:" "$LATEST_LOG" | tail -1
    else
        echo "  ⚠️  尚未生成交易信号"
    fi
    
    # 检查订单提交
    echo "💼 订单提交检查:"
    if grep -q "Submitting\|Placing\|Order" "$LATEST_LOG"; then
        echo "  ✅ 已提交订单"
        grep -E "Submitting|Placing|Order" "$LATEST_LOG" | tail -3
    else
        echo "  ⚠️  尚未提交订单"
    fi
    
    # 检查错误
    echo "⚠️  错误检查:"
    ERROR_COUNT=$(grep -ci "error\|exception\|fail" "$LATEST_LOG" 2>/dev/null || echo "0")
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "  ⚠️  发现 $ERROR_COUNT 个错误/异常"
        echo "  最新错误:"
        grep -i "error\|exception\|fail" "$LATEST_LOG" | tail -3
    else
        echo "  ✅ 未发现错误"
    fi
    
    echo ""
    echo "=========================================="
    echo "📝 最新日志（最后10行）:"
    echo "=========================================="
    tail -10 "$LATEST_LOG" | sed 's/^/  /'
    
else
    echo "❌ 未找到日志文件"
fi

echo ""
echo "=========================================="
echo "监控完成"
echo "=========================================="

