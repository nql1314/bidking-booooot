# -*- coding: utf-8 -*-
"""visual_config_schema 各字段的中文 label 与 description。"""

from __future__ import annotations

# path -> {"label": 短标题, "description": 悬浮说明}
FIELD_META: dict[str, dict[str, str]] = {
    "advisor.role": {
        "label": "顾问角色",
        "description": "画板估价使用的顾问/管线标识（如 aisha），与 bot 的 selected_mode 可独立。",
    },
    # ── automation ──────────────────────────────────────────────────────────
    "automation.aisha_round4_tool_min_vacant": {
        "label": "第4回合空置门槛",
        "description": "爱莎第4回合道具门控：几何空置格 + 自动 phantom_vac_* 占格须 ≥ 此值，且 Q5 统计已知时，才允许使用道具。",
    },
    "automation.bid_cap_price": {
        "label": "封顶价",
        "description": "单局出价上限；计算价超过此值时截断到此价格。0 表示不启用封顶。",
    },
    "automation.bid_cap_skip_when_total_above": {
        "label": "保险价",
        "description": "已知物品总价（不含第4回合空置区自动 phantom_vac 填充）超过此值时不再应用封顶。0 表示与封顶价相同，推荐设为游戏内保险价",
    },
    "automation.bid_ratio_by_round.1": {
        "label": "第1回合系数",
        "description": "第1回合最终出价 ≈ 基础估价 × 系数；可 >1 以抬高靠近天花板时的出价；不得超过 1.5。",
    },
    "automation.bid_ratio_by_round.2": {
        "label": "第2回合系数",
        "description": "第2回合最终出价 ≈ 基础估价 × 系数；不得超过 1.5。",
    },
    "automation.bid_ratio_by_round.3": {
        "label": "第3回合系数",
        "description": "第3回合最终出价 ≈ 基础估价 × 系数；不得超过 1.5。",
    },
    "automation.bid_ratio_by_round.4": {
        "label": "第4回合系数",
        "description": "第4回合最终出价 ≈ 基础估价 × 系数；不得超过 1.5。",
    },
    "automation.bid_ratio_by_round.5": {
        "label": "第5回合系数",
        "description": "第5回合最终出价 ≈ 基础估价 × 系数；不得超过 1.5。",
    },
    "automation.aisha_bid_ratio_by_round_when_q5_known.5": {
        "label": "艾莎第5回合（已知金总格）系数",
        "description": "艾莎且 event_stats 已公开 q5_grid_count 时第5回合专用系数。",
    },
    "automation.aisha_bid_ratio_by_round_when_q5_known.default": {
        "label": "艾莎第6+回合（已知金总格）默认系数",
        "description": "艾莎已知金总格且回合≥6 时未单独配置回合所用系数。",
    },
    "automation.bot_runner": {
        "label": "Bot 实现",
        "description": "启动时加载的 bot 模块名（如 fresh_aisha_bot），决定自动化主循环实现。",
    },
    "automation.cycle_rest_minutes": {
        "label": "大循环间隔（分钟）",
        "description": "每完成一整条 map_chain 后的休息分钟数；0 表示不休息。",
    },
    "automation.map_chain": {
        "label": "链式地图",
        "description": "按顺序执行的地图列表；每项含 map_id、本段局数 runs、本段道具回合 tool_rounds（1–5）；与 run_cycles 相乘为总局数。",
    },
    "automation.default_map": {
        "label": "默认地图键",
        "description": "未在面板选择地图时使用的 maps 键（如 \"450\"），对应 pricing.maps 文件名。",
    },
    "automation.default_runs": {
        "label": "默认局数",
        "description": "单次启动默认连续对局数（与 Bot 面板「局数」一致时的默认值）。",
    },
    "automation.enable_map_entry_money_check": {
        "label": "主界面资产准入检查",
        "description": "回到主界面时 OCR 当前资产并与 map_entry_money_by_map_id 比对；不足则自动停止 bot。关闭后跳过资产校验（UID 仍仅在会话首次回主界面时同步）。",
    },
    "automation.enable_aisha_round4_tool_vacant_gate": {
        "label": "爱莎第4回合空置门控",
        "description": "开启后：第4回合仅在空置格≥门槛且 Q5 网格统计已知时才使用道具。",
    },
    "automation.game_start_timeout_seconds": {
        "label": "开局等待超时（秒）",
        "description": "选图后等待「开始」界面出现的最大秒数，超时则重试或放弃本局。",
    },
    "automation.map_select_no_start_esc_after": {
        "label": "无开局连按 ESC 次数",
        "description": "连续多少次未检测到开局后按 ESC 返回，避免卡在选图/加载界面。",
    },
    "automation.post_confirm_escape_block_seconds": {
        "label": "确认后禁 ESC（秒）",
        "description": "出价确认后在此秒数内不响应 unknown 状态的 ESC 逃脱，防止误触打断流程。",
    },
    "automation.run_cycles": {
        "label": "大循环轮数",
        "description": "整条 map_chain 重复执行的遍数；总局数 = 链内各段 runs 之和 × 本项。",
    },
    "automation.selected_mode": {
        "label": "策略模式",
        "description": "Bot 出价/估价管线标识（如 aisha_premium），影响顾问与后处理逻辑。",
    },
    "automation.tool_rounds": {
        "label": "使用道具回合",
        "description": "在哪些回合号自动点击道具，整数列表（如 1,2,3,4）。",
    },
    "automation.tool_skip_vacant_threshold": {
        "label": "道具跳过空置阈值",
        "description": "空置格数量低于此值时跳过该回合道具（通用阈值；爱莎门控另见第4回合项）。",
    },
    "automation.unknown_escape_cooldown_seconds": {
        "label": "unknown 逃脱冷却（秒）",
        "description": "棋盘处于 unknown 时两次 ESC 逃脱之间的最短间隔，避免连按。",
    },
    "automation.warehouse_auto_sort.enabled": {
        "label": "仓库自动整理",
        "description": "每局开始前是否自动打开仓库并执行一键整理。",
    },
    "automation.warehouse_auto_sort.wait_after_auto_sort_click_seconds": {
        "label": "整理按钮后等待（秒）",
        "description": "点击仓库内「自动整理」后等待界面刷新的秒数。",
    },
    "automation.warehouse_auto_sort.wait_after_warehouse_click_seconds": {
        "label": "开仓库后等待（秒）",
        "description": "点击打开仓库按钮后等待界面出现的秒数。",
    },
    # ── board_snapshot ──────────────────────────────────────────────────────
    "board_snapshot.enabled": {
        "label": "启用棋盘快照",
        "description": "是否与 data/board_snapshot.json 同步读写，供画板与 bot 共享棋盘状态。",
    },
    "board_snapshot.self_user_uid": {
        "label": "本人 UID",
        "description": "快照中标记己方棋子的用户 ID，用于排除本人格子参与估价/空置统计。",
    },
    # ── grid_view ───────────────────────────────────────────────────────────
    "grid_view.fraud_empty_cells_algorithm": {
        "label": "空置区诈骗格算法",
        "description": "估算空格子时剔除「诈骗格」：tiling_strict（严格平铺）、tiling、none（不剔除）。",
    },
    "grid_view.unknown_bg": {
        "label": "未知格背景色",
        "description": "画板上未识别/未知格子的填充颜色，十六进制如 #1a7394。",
    },
    "grid_view.auto_expand_log_contour": {
        "label": "自动扩展轮廓",
        "description": "与 phantom_vac 自动填充分开；开启后刷新画板时在填充之后应用分析层轮廓推断（早期回合仅权重价扩形）。",
    },
    # ── humanize ────────────────────────────────────────────────────────────
    "humanize.enabled": {
        "label": "启用拟人化",
        "description": "总开关：鼠标轨迹抖动、移动耗时、出价输入随机间隔等；关闭则尽量瞬时操作。",
    },
    "humanize.click_jitter_pixels": {
        "label": "点击抖动（像素）",
        "description": "点击目标坐标时在半径内随机偏移的最大像素数。",
    },
    "humanize.move_duration_min": {
        "label": "移动耗时下限（秒）",
        "description": "鼠标从当前位置移到目标的最短动画时长。",
    },
    "humanize.move_duration_max": {
        "label": "移动耗时上限（秒）",
        "description": "鼠标移动动画的最长时长。",
    },
    "humanize.move_steps_min": {
        "label": "移动步数下限",
        "description": "模拟移动路径的最少插值步数。",
    },
    "humanize.move_steps_max": {
        "label": "移动步数上限",
        "description": "模拟移动路径的最多插值步数。",
    },
    "humanize.arc_strength_min": {
        "label": "弧线强度下限",
        "description": "鼠标轨迹弯曲程度随机范围的下限。",
    },
    "humanize.arc_strength_max": {
        "label": "弧线强度上限",
        "description": "鼠标轨迹弯曲程度随机范围的上限。",
    },
    "humanize.pre_click_delay_min": {
        "label": "点击前延迟下限（秒）",
        "description": "移动到目标后、按下鼠标前的最短等待。",
    },
    "humanize.pre_click_delay_max": {
        "label": "点击前延迟上限（秒）",
        "description": "移动到目标后、按下鼠标前的最长等待。",
    },
    "humanize.pre_select_all_delay_min": {
        "label": "全选前延迟下限（秒）",
        "description": "出价框全选（Ctrl+A）前的最短等待。",
    },
    "humanize.pre_select_all_delay_max": {
        "label": "全选前延迟上限（秒）",
        "description": "出价框全选前的最长等待。",
    },
    "humanize.post_select_all_delay_scale_min": {
        "label": "全选后延迟缩放下限",
        "description": "全选后额外等待 = 基准 × 此随机缩放的下限。",
    },
    "humanize.post_select_all_delay_scale_max": {
        "label": "全选后延迟缩放上限",
        "description": "全选后额外等待的随机缩放上限。",
    },
    "humanize.price_char_interval_min": {
        "label": "出价键入间隔下限（秒）",
        "description": "逐字输入出价数字时，相邻按键的最短间隔。",
    },
    "humanize.price_char_interval_max": {
        "label": "出价键入间隔上限（秒）",
        "description": "逐字输入出价数字时，相邻按键的最长间隔。",
    },
    "humanize.price_stutter_probability": {
        "label": "出价卡顿概率",
        "description": "输入出价时随机插入一次额外停顿的概率（0~1）。",
    },
    "humanize.price_stutter_extra_min": {
        "label": "卡顿额外时长下限（秒）",
        "description": "触发输入卡顿时额外等待的最短秒数。",
    },
    "humanize.price_stutter_extra_max": {
        "label": "卡顿额外时长上限（秒）",
        "description": "触发输入卡顿时额外等待的最长秒数。",
    },
    # ── pricing ─────────────────────────────────────────────────────────────
    "pricing.enable_big_gold_adjustment": {
        "label": "启用大金调整",
        "description": "是否对棋盘上的「大金」等高价值格应用额外出价调整逻辑。",
    },
    "pricing.enable_late_round_low_bid_surrender": {
        "label": "后期低价认输",
        "description": "开启后：超过指定回合且出价低于阈值时，强制改为认输价（默认 886）。",
    },
    "pricing.enable_opponent_bid_adjustment": {
        "label": "对手出价修正",
        "description": "是否根据对手历史出价/排名对己方出价做修正。",
    },
    "pricing.enable_vacant_red_floor_ceiling_pick": {
        "label": "空置红格地板天花板选取",
        "description": "空置区存在红格时，是否在地板价与天花板价之间按模式选取参考价。",
    },
    "pricing.fallback_bid_price": {
        "label": "兜底价",
        "description": "无法算出有效估价时使用的固定出价。",
    },
    "pricing.grid_avg_infer_max_grid_count": {
        "label": "网格均价最大格数",
        "description": "用网格均价推断未知价值时，最多纳入多少个格子参与平均。",
    },
    "pricing.grid_avg_infer_max_item_count": {
        "label": "网格均价最大物品种类",
        "description": "网格均价推断时参与统计的不同物品种类上限。",
    },
    "pricing.infer_vacant_rect_phantoms": {
        "label": "第4回合空格自动填充",
        "description": "第4回合及之后：空置区近似实心矩形 → 自动 phantom_vac；低档总格齐备前日志轮廓按 CSV 权重价选形，齐备后迭代 merge_expand。",
    },
    "pricing.late_round_low_bid_surrender_after_round": {
        "label": "认输生效回合",
        "description": "从第几回合起（含该回合）启用后期低价认输。",
    },
    "pricing.late_round_low_bid_surrender_below": {
        "label": "认输出价阈值",
        "description": "计算出价低于此值时触发认输价替换。",
    },
    "pricing.late_round_low_bid_surrender_bid": {
        "label": "认输固定出价",
        "description": "触发后期低价认输时强制使用的出价（常为 886）。",
    },
    "pricing.price_avg_infer_max_item_count": {
        "label": "均价推断最大物品种类",
        "description": "按物品均价推断未知价值时，参与统计的物品种类上限。",
    },
    "pricing.secret_auction_rank_opponent_multipliers.1": {
        "label": "秘拍第1名对手系数",
        "description": "隐秘拍卖地图：对手排名第1时的出价乘数。",
    },
    "pricing.secret_auction_rank_opponent_multipliers.2": {
        "label": "秘拍第2名对手系数",
        "description": "隐秘拍卖地图：对手排名第2时的出价乘数。",
    },
    "pricing.secret_auction_rank_opponent_multipliers.3": {
        "label": "秘拍第3名对手系数",
        "description": "隐秘拍卖地图：对手排名第3时的出价乘数。",
    },
    "pricing.secret_auction_rank_opponent_multipliers.4": {
        "label": "秘拍第4名对手系数",
        "description": "隐秘拍卖地图：对手排名第4时的出价乘数。",
    },
    "pricing.secret_auction_rank_opponent_multipliers.default": {
        "label": "秘拍默认对手系数",
        "description": "隐秘拍卖地图：未匹配到具体名次时使用的默认乘数。",
    },
    "pricing.vacant_red_floor_ceiling_pick_mode": {
        "label": "空置红格选取模式",
        "description": "normal / aggressive / force_gold_red：红格在地板与天花板之间的参考价倾向；force_gold_red 强制采用金红价。",
    },
    # ── safety ──────────────────────────────────────────────────────────────
    "safety.bring_window_to_front": {
        "label": "操作前置前窗口",
        "description": "点击/输入前是否将游戏窗口置于前台。",
    },
    "safety.confirm_after_type": {
        "label": "输入后确认点击",
        "description": "键入出价后是否再点击确认区域（与 OCR 校验配合）。",
    },
    "safety.dry_run": {
        "label": "演习模式",
        "description": "开启后只记录日志，不实际点击/输入（用于调试策略）。",
    },
    "safety.failsafe": {
        "label": "PyAutoGUI 保险丝",
        "description": "鼠标甩到屏幕角落时中止自动化（PyAutoGUI FAILSAFE）。",
    },
    "safety.move_pause_seconds": {
        "label": "移动后停顿（秒）",
        "description": "每次鼠标移动完成后的固定停顿，降低操作过快被检测风险。",
    },
    "safety.park_mouse_after_clicks": {
        "label": "点击后停放鼠标",
        "description": "每次点击序列结束后是否将鼠标移到安全停放坐标。",
    },
    "safety.skip_round_bid_button_ocr_gate": {
        "label": "跳过出价按钮 OCR 门控",
        "description": "为 true 时不等待「可出价」状态 OCR，直接进入出价（加快但可能抢拍）。",
    },
    "safety.stuck_after_handled_round.enabled": {
        "label": "卡死恢复",
        "description": "连续多轮轮询无进展时，执行预设屏幕坐标点击尝试解除卡死。",
    },
    "safety.stuck_after_handled_round.consecutive_poll_threshold": {
        "label": "卡死判定轮询次数",
        "description": "连续多少次主循环轮询仍无状态变化则触发卡死恢复点击。",
    },
    "safety.stuck_after_handled_round.between_clicks_seconds": {
        "label": "卡死恢复点击间隔（秒）",
        "description": "卡死恢复两次屏幕点击之间的等待秒数。",
    },
    "safety.verify_bid_confirm_snapshot": {
        "label": "出价快照确认重试",
        "description": "开启后轮询画板快照，见到 C2S_34_game_bid 才视为出价完成，否则重试 UI。",
    },
    # ── timing ──────────────────────────────────────────────────────────────
    "timing.after_bid_confirm_wait_seconds": {
        "label": "确认出价后等待（秒）",
        "description": "点击出价确认后等待界面切换的秒数。",
    },
    "timing.before_end_reward_click_seconds": {
        "label": "结算页出售前等待（秒）",
        "description": "检测到对局结束、进入奖励结算页后，点击「出售」按钮前的等待秒数。",
    },
    "timing.after_map_select_wait_seconds": {
        "label": "开始匹配后等待（秒）",
        "description": "大厅点地图进入详情后，点击开始匹配（post_continue_confirm）再等待加载/开局的秒数。",
    },
    "timing.bid_confirm_retry_pause_seconds": {
        "label": "确认重试间隔（秒）",
        "description": "每次出价 UI 后等待快照 C2S_34 的窗口；未见事件则按此间隔重试 UI。",
    },
    "timing.bid_confirm_snapshot_poll_seconds": {
        "label": "快照轮询间隔（秒）",
        "description": "等待 C2S_34 时两次读取 board_snapshot 的间隔。",
    },
    "timing.bid_confirm_verify_max_seconds": {
        "label": "确认校验最长时间（秒）",
        "description": "轮询快照直至见到 C2S_34_game_bid、进入下一回合或 game over 的最长总时长。",
    },
    "timing.click_pause_seconds": {
        "label": "点击间隔（秒）",
        "description": "连续两次点击之间的默认停顿。",
    },
    "timing.poll_seconds": {
        "label": "主循环轮询间隔（秒）",
        "description": "Bot 主循环每次检测棋盘/界面状态的间隔。",
    },
    "timing.reward_continue_debounce_seconds": {
        "label": "奖励继续防抖（秒）",
        "description": "结算界面点击「继续」后的防抖时间，避免重复点击。",
    },
    "timing.round1_extra_wait_seconds": {
        "label": "第1回合额外等待（秒）",
        "description": "第1回合检测到可出价后额外等待，便于棋盘信息稳定。",
    },
    "timing.round_bid_button_gate_max_seconds": {
        "label": "出价按钮门控超时（秒）",
        "description": "等待 OCR 识别「可出价」状态的最长秒数。",
    },
    "timing.round_bid_button_gate_poll_seconds": {
        "label": "出价门控轮询间隔（秒）",
        "description": "等待可出价 OCR 时每次重试的间隔。",
    },
    "timing.round_detect_wait_seconds": {
        "label": "回合检测等待（秒）",
        "description": "检测到新回合后等待界面稳定的秒数。",
    },
    "timing.transition_debounce_seconds": {
        "label": "状态切换防抖（秒）",
        "description": "界面状态切换后的防抖时间，避免重复触发同一过渡。",
    },
    # ── viewer ──────────────────────────────────────────────────────────────
    "viewer.show_bot_runner": {
        "label": "显示启动 Bot 按钮",
        "description": "主界面是否显示「启动 Bot」入口。",
    },
    "viewer.game_report_max_matches": {
        "label": "全局报表最大局数",
        "description": "全局对局报表保留局数上限；启动时裁剪最早记录，0 为不限制。",
    },
}
