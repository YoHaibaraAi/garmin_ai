# garmin-ai

`garmin-ai` 是一个本地 Garmin Connect CLI 工具，用来把 Garmin 运动、身体指标和 FIT 文件解析结果整理成适合 AI 分析的结构化数据。

它只做本地命令行，不提供 Web 服务，不做 MCP。默认输出 JSON，错误也会输出 JSON，方便人类、Claude Code、Codex、Skill 或其他脚本通过 shell 调用。

## 功能概览

- 使用 `python-garminconnect` 登录 Garmin Connect 并读取数据
- 使用 Garmin 官方 `garmin-fit-sdk` 解析 FIT 文件
- 默认获取最近 1 条跑步
- 输出用户基础信息、当前身体指标、跑步 summary、当天身体指标、分段数据
- 区分 Garmin Connect 分段、FIT 原始 Lap、程序计算的固定每公里分段
- full 模式导出 CSV、Parquet、JSON、HTML 图表和原始 FIT 文件
- html 模式导出浏览器可读的总览页、单活动报告和图表
- Garmin API 单个字段或接口失败时不会让整个 `base` 命令失败
- 缺失或失败的数据会在 `data_quality` 中标记

## 项目结构

```text
garmin-ai/
├── pyproject.toml
├── README.md
├── data/
│   ├── fit/
│   ├── cache/
│   └── exports/
├── src/
│   └── garmin_ai/
│       ├── cli.py
│       ├── auth.py
│       ├── errors.py
│       ├── garmin_client.py
│       ├── fit_downloader.py
│       ├── fit_parser.py
│       ├── split_calculator.py
│       ├── metrics_collector.py
│       ├── exporter.py
│       ├── chart_builder.py
│       ├── utils.py
│       └── models.py
└── skills/
    └── garmin-running-analysis/
        └── SKILL.md
```

实际代码采用 `src` layout，CLI 入口是：

```toml
[project.scripts]
garmin-ai = "garmin_ai.cli:app"
```

## 环境要求

- Python 3.12 推荐
- 项目声明 Python `>=3.11`
- 当前使用 GitHub `cyberjunky/python-garminconnect` 的 `v0.3.4` tag，因为该版本修复了中国区账号 DI OAuth2 token 刷新走 `diauth.garmin.cn` 的问题
- `garminconnect` 当前包元数据要求 Python `>=3.12`，所以实际使用建议用 Python 3.12
- 使用 `uv` 管理依赖和运行命令

依赖包括：

- `garminconnect`
- `curl_cffi`
- `garmin-fit-sdk`
- `typer`
- `rich`
- `pandas`
- `pyarrow`
- `plotly`

## 安装/初始化

在项目根目录运行：

```bash
uv sync
```

查看 CLI 是否可用：

```bash
uv run garmin-ai --help
```

查看 `base` 命令参数：

```bash
uv run garmin-ai base --help
```

## 认证

首次使用前运行：

```bash
uv run garmin-ai auth
```

命令会交互式提示输入：

```text
Garmin email:
Garmin password:
```

如果 Garmin 账号开启了两步验证，登录流程会继续提示输入验证码。

认证成功后，token 会保存到：

```text
~/.garminconnect
```

当前默认登录 Garmin 中国区账号。代码中创建 Garmin 客户端时使用 `is_cn=True`，所以 `auth` 和后续 `base` 查询都会走国内账号环境。

项目不会保存账号密码，也不会要求把账号密码写入 `.env`、配置文件或代码。

普通查询命令不会交互式输入验证码。只有 `garmin-ai auth` 负责登录、两步验证和 token 初始化。

## 基础用法

获取最近 1 条跑步基础上下文：

```bash
uv run garmin-ai base
```

等价于：

```bash
uv run garmin-ai base --limit 1 --no-full --json
```

获取最近 5 条跑步：

```bash
uv run garmin-ai base --limit 5
```

默认会在 `current_metrics.sleep` 返回最近 7 天精简睡眠摘要。调整天数：

```bash
uv run garmin-ai base --limit 1 --sleep-days 7 --json
```

输出保存成 JSON 文件：

```bash
uv run garmin-ai base --limit 1 --output ./data/exports/base_context.json
```

输出到目录，并额外导出基础 CSV/JSON：

```bash
uv run garmin-ai base --limit 1 --output ./data/exports/base
```

## html 模式

html 模式会生成适合人直接浏览的 HTML 导出：顶层 `index.html` 是最近跑步总览，每条活动目录下的 `index.html` 是单次跑步报告，并内嵌 Plotly 图表。HTML 模式会将最近 N 天睡眠数据渲染为摘要卡片、每日表格和趋势图。

```bash
uv run garmin-ai base --limit 5 --mode html --output ./data/exports/html
```

图表默认使用距离作为 x 轴。需要按时间查看时使用：

```bash
uv run garmin-ai base --limit 5 --mode html --chart-x time --output ./data/exports/html
```

生成后直接打开：

```text
data/exports/html/<run_id>/index.html
```

如果不传 `--output`，html 模式默认写入：

```text
data/exports/latest/<run_id>/
```

目录型导出每次都会创建一个独立的 `<run_id>` 子目录，格式类似 `20260531-143012`，避免覆盖上一次导出。导出完成后会在同级目录生成同名压缩包，例如 `<run_id>.zip`。直接指定 `.json` 文件时例外，会写入该 JSON 文件本身，不生成压缩包。

## compact 精简模式

compact 模式用于生成更省 token 的报告。顶层 `index.html` 的 Current Metrics 表和 base HTML 保持一致，并保留 Sleep Summary 表格与 Recent Runs，但去除睡眠趋势图；单次活动 `index.html` 去除图表，只保留 Summary 和 Connect Splits。compact 模式不会生成 `charts.html`，也不会下载/解析 FIT。

输出精简 HTML：

```bash
uv run garmin-ai base --limit 5 --mode compact --compact-format html --output ./data/exports/compact
```

输出精简 JSON：

```bash
uv run garmin-ai base --limit 5 --mode compact --compact-format json --output ./data/exports/compact-json
uv run garmin-ai base --limit 5 --mode compact --compact-format json --output ./data/exports/compact.json
```

## full 模式

full 模式会下载并保留原始 FIT 文件，导出逐点 records、跑步动态、GPS、事件、设备信息、开发者字段和 HTML 图表。

```bash
uv run garmin-ai base --limit 1 --mode full --output ./data/exports/latest
```

full 模式也支持切换图表 x 轴：

```bash
uv run garmin-ai base --limit 1 --mode full --chart-x distance --output ./data/exports/latest
uv run garmin-ai base --limit 1 --mode full --chart-x time --output ./data/exports/latest
```

`--full` 仍然可用，等价于 `--mode full`。

full 模式下，主 JSON 不会直接塞入完整 records，只返回文件路径和统计信息，避免输出过大。

## 输出目录

### FIT 缓存

下载的原始 FIT 缓存在：

```text
data/fit/
```

文件名类似：

```text
data/fit/123456789.fit
```

如果使用默认 `--cache`，同一个活动再次运行时会复用已有 FIT 文件。

强制重新下载：

```bash
uv run garmin-ai base --limit 1 --no-cache
```

### full 模式导出

示例命令：

```bash
uv run garmin-ai base --limit 1 --mode full --output ./data/exports/latest
```

输出结构：

```text
data/exports/latest/<run_id>/
├── base_context.json
├── recent_runs.json
├── index.html
└── 123456789/
    ├── context.json
    ├── summary.json
    ├── connect_splits.json
    ├── fit_laps.csv
    ├── km_splits.csv
    ├── records.csv
    ├── records.parquet
    ├── running_dynamics.csv
    ├── gps.csv
    ├── events.csv
    ├── device_info.json
    ├── developer_fields.json
    ├── original.fit
    └── charts.html

data/exports/latest/<run_id>.zip
```

### html 模式导出

示例命令：

```bash
uv run garmin-ai base --limit 5 --mode html --output ./data/exports/html
```

输出结构：

```text
data/exports/html/<run_id>/
├── base_context.json
├── recent_runs.json
├── index.html
└── 123456789/
    ├── context.json
    ├── index.html
    └── charts.html

data/exports/html/<run_id>.zip
```

html 模式不会导出 `records.csv`、`records.parquet`、`original.fit` 等 full 模式的大文件，适合只想人工查看总览、分段和曲线时使用。

### compact 模式导出

示例命令：

```bash
uv run garmin-ai base --limit 5 --mode compact --compact-format html --output ./data/exports/compact
```

HTML 输出结构：

```text
data/exports/compact/<run_id>/
├── base_context.json
├── recent_runs.json
├── index.html
└── 123456789/
    ├── context.json
    ├── summary.json
    ├── connect_splits.json
    └── index.html

data/exports/compact/<run_id>.zip
```

JSON 输出结构：

```text
data/exports/compact-json/<run_id>/
├── base_context.json
├── recent_runs.json
└── 123456789/
    ├── context.json
    ├── summary.json
    └── connect_splits.json

data/exports/compact-json/<run_id>.zip
```

compact 模式只保留顶层身体指标、睡眠摘要、最近跑步 summary 和 Connect Splits，适合把结果直接交给 AI 做低 token 分析。

### CSV 文件说明

CSV 文件在每个活动目录下：

```text
data/exports/latest/<run_id>/<activity_id>/
```

常用文件：

| 文件 | 来源 | 用途 |
| --- | --- | --- |
| `fit_laps.csv` | FIT `lap_mesgs` | 手表写入的原始 Lap，可能是自动 Lap、手动 Lap 或训练课分段 |
| `km_splits.csv` | FIT `record_mesgs` | 程序按固定每公里重新计算，适合稳定分析配速/心率/步频/功率 |
| `records.csv` | FIT `record_mesgs` | 逐点记录，通常是逐秒或非固定间隔 |
| `running_dynamics.csv` | FIT records 中的跑步动态字段 | 垂直振幅、触地时间、触地平衡、步幅、垂直比等 |
| `gps.csv` | FIT records 中的经纬度 | GPS 轨迹点 |
| `events.csv` | FIT `event_mesgs` | 事件记录 |

## 导出文件说明

导出目录会根据模式包含 JSON、CSV、Parquet、HTML 和原始 FIT 文件。先按文件粒度理解它们：

- 顶层文件描述本次命令的整体结果
- 单条活动 JSON 描述某一次跑步的摘要和上下文
- CSV / Parquet 保存可表格化分析的数据
- HTML 用于人工浏览总览、单活动报告和图表
- `original.fit` 是最原始的数据来源

### 顶层文件是什么

| 文件 | 是什么 | 什么时候用 |
| --- | --- | --- |
| `base_context.json` | 本次 `garmin-ai base` 的完整上下文，包含用户信息、当前身体指标、最近跑步列表和每条跑步的关键数据 | 直接交给 AI 做整体分析 |
| `recent_runs.json` | `base_context.json` 里的 `recent_runs` 单独拆出来 | 只关心跑步活动，不关心用户基础信息时使用 |
| `index.html` | 导出目录的 HTML 入口页；html 模式展示总览表，full 模式链接到每条活动的 `charts.html` | 人工浏览入口 |

`base_context.json` 不会内嵌完整逐点 `records`，所以适合作为默认 AI 上下文。

### 单条活动文件是什么

这些文件位于：

```text
data/exports/latest/<run_id>/<activity_id>/
```

| 文件 | 是什么 | 来源 | 什么时候用 |
| --- | --- | --- | --- |
| `context.json` | 单条跑步的完整上下文 | `base` 汇总结果 | 把某一条跑步单独交给 AI 分析 |
| `summary.json` | 单条跑步概要数据 | Garmin Connect 活动 summary，部分字段归一化计算 | 快速看距离、时间、配速、心率、训练效果、设备等整体表现 |
| `connect_splits.json` | Garmin Connect 返回的分段、圈、训练段或摘要 | Garmin Connect split 相关 API | 对照 Garmin Connect 页面上的分段数据 |
| `fit_laps.csv` | 设备写入 FIT 的原始 Lap | FIT `lap_mesgs` | 分析自动 Lap、手动 Lap、训练课分段 |
| `km_splits.csv` | 程序按固定每公里重新计算的分段 | FIT `record_mesgs` | 分析每公里配速、心率、步频、功率和跑步动态变化 |
| `records.csv` | FIT 逐点记录 | FIT `record_mesgs` | 用户要求逐秒或逐点分析时使用 |
| `records.parquet` | 和 `records.csv` 内容相同的 Parquet 版本 | FIT `record_mesgs` | 大文件、批处理或 pandas/pyarrow 分析 |
| `running_dynamics.csv` | 从逐点记录中拆出的跑步动态 | FIT `record_mesgs` | 用户要求逐秒跑步动态分析时使用 |
| `gps.csv` | 从逐点记录中拆出的 GPS 轨迹点 | FIT `record_mesgs` | 用户明确要求路线、轨迹、地图、GPS 或路线相关分析时使用 |
| `events.csv` | 活动事件记录 | FIT `event_mesgs` | 排查暂停、恢复、Lap、训练阶段等事件 |
| `device_info.json` | FIT 中的设备信息 | FIT `device_info_mesgs` | 排查数据来自哪块表、哪台设备或哪些传感器 |
| `developer_fields.json` | FIT 中的开发者字段说明 | FIT `developer_data_id_mesgs`、`field_description_mesgs` | 排查特殊字段、第三方数据源或设备扩展数据 |
| `original.fit` | Garmin Connect 下载的原始 FIT 文件 | Garmin Connect original activity download | 重新解析、用其他 FIT 工具验证、排查 SDK 差异 |
| `charts.html` | 单条活动的 Plotly 静态图表 | `records`、`km_splits`、`gps` 等导出数据 | 详细分析时先看趋势图，再结合结构化数据 |
| `index.html` | html 模式的单条活动报告 | `summary`、`day_metrics`、`km_splits`、`fit_laps`、`connect_splits`、`charts.html` | 人工查看单次跑步 |

### 三个分段文件怎么选

| 文件 | 含义 | 是否一定每公里 | 推荐用途 |
| --- | --- | --- | --- |
| `connect_splits.json` | Garmin Connect 后台返回的分段/圈/训练段 | 不一定 | 对照 Garmin Connect 页面 |
| `fit_laps.csv` | 手表写入 FIT 的原始 Lap | 不一定 | 分析设备原始 Lap、手动 Lap、训练课阶段 |
| `km_splits.csv` | 程序按 FIT records 重新计算的固定每公里 | 是，最后一段可能不足 1 公里 | AI 分析配速、心率、步频、功率变化 |

如果目标是“跑步表现分析”，通常优先读 `km_splits.csv`。如果目标是“为什么 Garmin 页面这么显示”，优先看 `connect_splits.json`。如果目标是“手表当时怎么记圈”，优先看 `fit_laps.csv`。

### 逐点数据怎么选

| 文件 | 粒度 | 默认是否建议读取 | 说明 |
| --- | --- | --- | --- |
| `records.csv` | 活动逐点记录 | 只在用户要求逐秒/逐点分析时读取 | 文件可能较大，适合曲线和细节分析 |
| `running_dynamics.csv` | 逐点跑步动态 | 只在用户要求逐秒/跑步动态分析时读取 | 不同设备支持程度不同，可能为空 |
| `gps.csv` | 逐点 GPS | 默认不读取 | 除非用户要求路线、轨迹、GPS、地图、爬升位置或配速与路线关系 |

## 导出字段说明

这一节解释导出文件中的字段。字段缺失时会返回空值，不会伪造 Garmin 数据。

### `base_context.json` / `context.json` 字段

| 字段 | 含义 |
| --- | --- |
| `ok` | 命令是否成功 |
| `mode` | `basic`、`full` 或 `html` |
| `chart_x` | 图表 x 轴模式，`distance` 或 `time` |
| `generated_at` | 本次数据生成时间 |
| `profile` | 用户基础数据，如身高、年龄 |
| `current_metrics` | 当前或最近身体指标 |
| `recent_runs` | 最近跑步列表 |
| `activity_id` | Garmin 活动 ID |
| `date` | 活动日期 |
| `summary` | 单次跑步概要 |
| `day_metrics` | 跑步当天身体指标 |
| `connect_splits` | Garmin Connect API 返回的分段 |
| `fit_laps` | FIT 原始 Lap |
| `km_splits` | 程序计算的固定每公里分段 |
| `full_data` | full 模式导出的文件路径和统计信息 |
| `html_data` | html 模式导出的文件路径和统计信息 |
| `data_quality` | 缺失、错误、降级信息 |

### `summary.json` 字段

| 字段 | 含义 |
| --- | --- |
| `activity_id` | Garmin 活动 ID |
| `activity_name` | 活动名称 |
| `activity_type` | 活动类型 |
| `start_time_local` | 本地开始时间 |
| `date` | 活动日期 |
| `distance_m` / `distance_km` | 距离，单位米/公里 |
| `duration_seconds` | 计时持续时间 |
| `moving_duration_seconds` | 移动时间 |
| `elapsed_seconds` | 总经过时间，包含暂停等 |
| `avg_pace_sec_per_km` | 平均配速，单位秒/公里 |
| `best_pace_sec_per_km` | 最快配速，单位秒/公里 |
| `avg_speed_mps` / `max_speed_mps` | 平均/最大速度，单位米/秒 |
| `avg_hr` / `max_hr` / `min_hr` | 平均/最大/最低心率 |
| `avg_cadence_spm` / `max_cadence_spm` | 平均/最大步频，单位步/分钟 |
| `avg_power_w` / `max_power_w` | 平均/最大功率，单位瓦 |
| `normalized_power_w` | 标准化功率 |
| `elevation_gain_m` / `elevation_loss_m` | 累计爬升/下降，单位米 |
| `min_altitude_m` / `max_altitude_m` | 最低/最高海拔，单位米 |
| `calories` | 消耗热量 |
| `training_effect_aerobic` | 有氧训练效果 |
| `training_effect_anaerobic` | 无氧训练效果 |
| `training_load` | 训练负荷 |
| `vo2max_from_activity` | 本次活动相关 VO2max |
| `recovery_time_hours` | 建议恢复时间，单位小时 |
| `avg_stride_length_m` | 平均步幅，单位米 |
| `avg_vertical_oscillation_mm` | 平均垂直振幅，单位毫米 |
| `avg_ground_contact_time_ms` | 平均触地时间，单位毫秒 |
| `avg_ground_contact_balance_left_percent` | 平均左侧触地平衡百分比 |
| `avg_vertical_ratio_percent` | 平均垂直比 |
| `temperature_avg_c` / `temperature_min_c` / `temperature_max_c` | 平均/最低/最高温度，单位摄氏度 |
| `device_name` | 设备名称 |
| `manufacturer` | 设备厂商 |

### `connect_splits.json` 字段

| 字段 | 含义 |
| --- | --- |
| `source` | 数据来自 `splits`、`typed_splits` 或 `split_summaries` |
| `raw` | Garmin Connect 返回的原始结构 |
| `split_index` | 分段序号 |
| `distance_m` | 分段距离，单位米 |
| `duration_seconds` | 分段用时，单位秒 |
| `avg_pace_sec_per_km` | 分段平均配速，单位秒/公里 |
| `avg_hr` / `max_hr` | 分段平均/最大心率 |
| `avg_cadence_spm` | 分段平均步频 |
| `avg_power_w` | 分段平均功率 |

### `fit_laps.csv` 字段

| 字段 | 含义 |
| --- | --- |
| `lap_index` | Lap 序号 |
| `start_time` / `end_time` | Lap 开始/结束时间 |
| `distance_m` | Lap 距离，单位米 |
| `duration_seconds` | Lap 计时持续时间 |
| `moving_duration_seconds` | Lap 移动时间 |
| `elapsed_seconds` | Lap 总经过时间 |
| `avg_pace_sec_per_km` | Lap 平均配速 |
| `avg_speed_mps` / `max_speed_mps` | Lap 平均/最大速度 |
| `avg_hr` / `max_hr` | Lap 平均/最大心率 |
| `avg_cadence_spm` / `max_cadence_spm` | Lap 平均/最大步频 |
| `avg_power_w` / `max_power_w` | Lap 平均/最大功率 |
| `elevation_gain_m` / `elevation_loss_m` | Lap 爬升/下降 |
| `calories` | Lap 消耗热量 |
| `lap_trigger` | Lap 触发方式，如自动、手动或训练阶段 |
| `sport` | 运动类型 |

### `km_splits.csv` 字段

| 字段 | 含义 |
| --- | --- |
| `km_index` | 第几个公里分段 |
| `partial` | 是否为不足 1 公里的尾段 |
| `start_distance_m` / `end_distance_m` | 分段起止距离 |
| `distance_m` | 分段实际距离 |
| `start_time` / `end_time` | 分段起止时间 |
| `duration_seconds` | 分段用时 |
| `pace_sec_per_km` | 分段配速，单位秒/公里 |
| `avg_speed_mps` / `max_speed_mps` | 平均/最大速度 |
| `avg_hr` / `max_hr` / `min_hr` | 平均/最大/最低心率 |
| `avg_cadence_spm` / `max_cadence_spm` | 平均/最大步频 |
| `avg_power_w` / `max_power_w` | 平均/最大功率 |
| `avg_stride_length_m` | 平均步幅 |
| `avg_vertical_oscillation_mm` | 平均垂直振幅 |
| `avg_ground_contact_time_ms` | 平均触地时间 |
| `avg_ground_contact_balance_left_percent` | 平均左侧触地平衡百分比 |
| `avg_vertical_ratio_percent` | 平均垂直比 |
| `elevation_gain_m` / `elevation_loss_m` | 分段爬升/下降 |
| `start_lat` / `start_lon` | 分段起点经纬度 |
| `end_lat` / `end_lon` | 分段终点经纬度 |

### `records.csv` / `records.parquet` 字段

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 记录时间 |
| `elapsed_seconds` | 从活动第一条记录开始经过的秒数 |
| `distance_m` | 累计距离，单位米 |
| `speed_mps` | 当前速度，单位米/秒 |
| `pace_sec_per_km` | 当前配速，单位秒/公里 |
| `heart_rate` | 心率 |
| `cadence_spm` | 步频，单位步/分钟 |
| `power_w` | 功率，单位瓦 |
| `altitude_m` | 海拔，单位米 |
| `temperature_c` | 温度，单位摄氏度 |
| `lat` / `lon` | 经纬度 |
| `vertical_oscillation_mm` | 垂直振幅 |
| `ground_contact_time_ms` | 触地时间 |
| `ground_contact_balance_left_percent` | 左侧触地平衡百分比 |
| `stride_length_m` | 步幅 |
| `vertical_ratio_percent` | 垂直比 |

### `running_dynamics.csv` 字段

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 记录时间 |
| `distance_m` | 累计距离 |
| `vertical_oscillation_mm` | 垂直振幅 |
| `ground_contact_time_ms` | 触地时间 |
| `ground_contact_balance_left_percent` | 左侧触地平衡百分比 |
| `stride_length_m` | 步幅 |
| `vertical_ratio_percent` | 垂直比 |

并不是所有设备都会记录跑步动态。如果设备不支持或没有佩戴对应传感器，这个文件可能为空。

### `gps.csv` 字段

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 记录时间 |
| `distance_m` | 累计距离 |
| `lat` / `lon` | 经纬度 |
| `altitude_m` | 海拔 |

如果活动是室内跑、跑步机或设备没有 GPS，这个文件可能为空。默认分析不读取 GPS，除非用户明确要求路线、轨迹、地图或路线相关分析。

### `events.csv` 字段

`events.csv` 保留 FIT `event_mesgs` 的原始事件字段，不同设备差异较大。常见含义包括开始、停止、暂停、恢复、Lap 事件和训练阶段事件。

### `device_info.json` / `developer_fields.json` 字段

这两个文件尽量保留 FIT 原始结构。字段取决于设备、传感器和 FIT 文件内容，主要用于排查设备来源、传感器来源、软件版本、产品 ID 和开发者扩展字段。

## 数据使用优先级

不同分析任务建议读不同文件：

| 任务 | 优先使用 |
| --- | --- |
| 快速总结最近一次跑步 | `base_context.json` 或 `context.json` |
| 分析整体强度 | `summary.json`、`day_metrics` |
| 分析每公里配速/心率/步频/功率 | `km_splits.csv` |
| 分析手表原始 Lap | `fit_laps.csv` |
| 对照 Garmin Connect 分段 | `connect_splits.json` |
| 逐秒/逐点曲线分析 | `records.csv` 或 `records.parquet` |
| 跑步动态分析 | `running_dynamics.csv` |
| 路线/GPS 分析 | `gps.csv` |
| 暂停/事件排查 | `events.csv` |
| 设备/传感器排查 | `device_info.json`、`developer_fields.json` |

## base JSON 输出结构

基础模式返回结构接近：

```json
{
  "ok": true,
  "mode": "basic",
  "generated_at": "2026-05-30T12:00:00+08:00",
  "profile": {
    "height_cm": null,
    "age": null,
    "max_heart_rate": null,
    "lactate_threshold_heart_rate": null
  },
  "current_metrics": {
    "date": "2026-05-30",
    "daily_max_heart_rate": null,
    "resting_heart_rate": null,
    "hrv": null,
    "weight_kg": null,
    "vo2max": null,
    "vo2max_precise": null,
    "sleep": {
      "days": 7,
      "items": [
        {
          "date": "2026-05-30",
          "sleep_score": null,
          "total_sleep_seconds": null,
          "total_sleep_hours": null,
          "deep_sleep_seconds": null,
          "light_sleep_seconds": null,
          "rem_sleep_seconds": null,
          "awake_seconds": null,
          "sleep_start": null,
          "sleep_end": null,
          "missing": true
        }
      ],
      "summary": {
        "avg_sleep_score": null,
        "avg_total_sleep_hours": null,
        "avg_deep_sleep_hours": null,
        "avg_light_sleep_hours": null,
        "avg_rem_sleep_hours": null,
        "avg_awake_minutes": null,
        "valid_days": 0,
        "missing_days": 7
      }
    }
  },
  "recent_runs": [
    {
      "activity_id": "123456789",
      "date": "2026-05-29",
      "summary": {},
      "day_metrics": {},
      "connect_splits": [],
      "fit_laps": [],
      "km_splits": [],
      "data_quality": {}
    }
  ],
  "data_quality": {}
}
```

full 模式中，每条 `recent_runs[]` 会额外包含：

```json
{
  "full_data": {
    "fit_file": "data/exports/latest/20260531-143012/123456789/original.fit",
    "records_file": "data/exports/latest/20260531-143012/123456789/records.csv",
    "records_parquet_file": "data/exports/latest/20260531-143012/123456789/records.parquet",
    "running_dynamics_file": "data/exports/latest/20260531-143012/123456789/running_dynamics.csv",
    "gps_file": "data/exports/latest/20260531-143012/123456789/gps.csv",
    "events_file": "data/exports/latest/20260531-143012/123456789/events.csv",
    "device_info_file": "data/exports/latest/20260531-143012/123456789/device_info.json",
    "developer_fields_file": "data/exports/latest/20260531-143012/123456789/developer_fields.json",
    "charts_file": "data/exports/latest/20260531-143012/123456789/charts.html",
    "record_count": 0,
    "gps_point_count": 0,
    "has_power": false,
    "has_running_dynamics": false
  }
}
```

html 模式中，每条 `recent_runs[]` 会额外包含：

```json
{
  "html_data": {
    "html_file": "data/exports/html/20260531-143012/123456789/index.html",
    "charts_file": "data/exports/html/20260531-143012/123456789/charts.html",
    "record_count": 0,
    "gps_point_count": 0,
    "has_power": false,
    "has_running_dynamics": false
  }
}
```

## 三类圈/分段的区别

`base` 中每条跑步都有三类分段：

```json
{
  "connect_splits": [],
  "fit_laps": [],
  "km_splits": []
}
```

### connect_splits

来源是 Garmin Connect API：

- `get_activity_splits(activity_id)`
- `get_activity_typed_splits(activity_id)`
- `get_activity_split_summaries(activity_id)`

它表示 Garmin Connect 返回的分段、圈、训练段或 split summary。它可能经过 Garmin 后台加工，不保证是每公里，也不保证等同于设备原始 Lap。

### fit_laps

来源是原始 FIT 文件中的：

```text
lap_mesgs
```

它更接近设备写入的原始圈数据。可能是：

- 自动 Lap
- 手动 Lap
- 训练课程分段
- 设备根据运动类型写入的其他 Lap

注意：`fit_laps` 也不一定是每公里。

### km_splits

来源是 FIT 文件中的：

```text
record_mesgs
```

程序按 `distance_m` 每 1000 米重新计算。它是固定每公里分段，适合 AI 分析：

- 配速变化
- 心率漂移
- 步频变化
- 功率变化
- 跑步动态变化
- GPS 和爬升变化

第一版不做复杂边界插值，但会保证稳定可用。

## summary 字段

每条跑步的 `summary` 会尽量包含：

- `activity_id`
- `activity_name`
- `activity_type`
- `start_time_local`
- `date`
- `distance_m`
- `distance_km`
- `duration_seconds`
- `moving_duration_seconds`
- `elapsed_seconds`
- `avg_pace_sec_per_km`
- `best_pace_sec_per_km`
- `avg_speed_mps`
- `max_speed_mps`
- `avg_hr`
- `max_hr`
- `min_hr`
- `avg_cadence_spm`
- `max_cadence_spm`
- `avg_power_w`
- `max_power_w`
- `normalized_power_w`
- `elevation_gain_m`
- `elevation_loss_m`
- `min_altitude_m`
- `max_altitude_m`
- `calories`
- `training_effect_aerobic`
- `training_effect_anaerobic`
- `training_load`
- `vo2max_from_activity`
- `recovery_time_hours`
- `avg_stride_length_m`
- `avg_vertical_oscillation_mm`
- `avg_ground_contact_time_ms`
- `avg_ground_contact_balance_left_percent`
- `avg_vertical_ratio_percent`
- `temperature_avg_c`
- `temperature_min_c`
- `temperature_max_c`
- `device_name`
- `manufacturer`

字段缺失时返回 `null`，不会伪造数据。

## 身体指标

`profile` 包含：

- `height_cm`
- `age`
- `max_heart_rate`
- `lactate_threshold_heart_rate`

`current_metrics` 和 `day_metrics` 包含：

- `date`
- `max_heart_rate`（仅 `current_metrics`，来自 `profile.max_heart_rate`，用于 HTML Current Metrics 表）
- `daily_max_heart_rate`
- `resting_heart_rate`
- `resting_heart_rate_7d_avg`
- `hrv`
- `hrv_7d_avg`
- `weight_kg`
- `vo2max`
- `vo2max_precise`
- `sleep`

`current_metrics.sleep` 默认是最近 7 天精简睡眠摘要，不包含 Garmin 原始睡眠响应。可用 `--sleep-days` 调整天数：

```bash
uv run garmin-ai base --limit 1 --sleep-days 14 --json
```

结构：

- `sleep.days`：统计天数
- `sleep.items[]`：每天一条精简睡眠数据
- `sleep.summary`：平均睡眠分、平均总睡眠时长、深睡/浅睡/REM/清醒均值和缺失天数

`day_metrics.sleep` 是单日精简睡眠摘要，字段包括：

- `date`
- `sleep_score`
- `total_sleep_seconds` / `total_sleep_hours`
- `deep_sleep_seconds`
- `light_sleep_seconds`
- `rem_sleep_seconds`
- `awake_seconds`
- `sleep_start` / `sleep_end`
- `missing`

`base` 不会输出 `sleepLevelsMap`、`sleepMovement`、`respiration`、`hrvReadings`、原始 sleep response 或完整 `sleepScores` 对象。如需原始睡眠数据，后续可以新增 `sleep --raw` 命令；当前版本不实现 raw 命令。

最大心率有三种不同语义：

- `profile.max_heart_rate`：个人最大心率设置，优先来自 Garmin 设备/设备设置接口，拿不到时可从 `~/.garmin-ai/config.json` 的 `max_heart_rate` 读取。
- `current_metrics.max_heart_rate`：同一个人最大心率值，会同步显示在 base 和 compact HTML 的 Current Metrics 表中。
- `current_metrics.daily_max_heart_rate` / `day_metrics.daily_max_heart_rate`：当天全天最高心率，来自每日心率或 summary 数据。
- `current_metrics.resting_heart_rate_7d_avg` / `current_metrics.hrv_7d_avg`：最近 7 天静息心率和 HRV 均值，会显示在 base 和 compact HTML 的 Current Metrics 表中。
- `activity.summary.max_hr`：某次活动中的最高心率。

本地配置个人最大心率：

```bash
uv run garmin-ai config set max-heart-rate 190
uv run garmin-ai config show
```

如果 Garmin 中国区接口没有返回个人最大心率，建议用上面的 `config set` 命令手动设置一次；后续 `base` 会自动读取本地配置。

`vo2max` 是 Garmin 展示值，优先来自用户资料中的 `userData.vo2MaxRunning`。`vo2max_precise` 是更精确的 VO2max 值，优先来自 `max_metrics[0].generic.vo2MaxPreciseValue`，更适合做趋势分析。如果只取到 `vo2max_precise`，`vo2max` 会使用其四舍五入值；如果只取到 `vo2max`，`vo2max_precise` 保持 `null`。

## 错误输出

错误也会 JSON 化。

### token 缺失或过期

```json
{
  "ok": false,
  "error_code": "AUTH_REQUIRED",
  "message": "Garmin token missing or expired. Run: garmin-ai auth"
}
```

处理方式：

```bash
uv run garmin-ai auth
```

### Garmin 限流

```json
{
  "ok": false,
  "error_code": "GARMIN_RATE_LIMITED",
  "message": "Garmin requests are rate limited. Try again later."
}
```

### FIT 下载失败

```json
{
  "ok": false,
  "error_code": "FIT_DOWNLOAD_ERROR",
  "message": "..."
}
```

### FIT 解析失败

```json
{
  "ok": false,
  "error_code": "FIT_PARSE_ERROR",
  "message": "..."
}
```

### 未知错误

```json
{
  "ok": false,
  "error_code": "UNKNOWN_ERROR",
  "message": "..."
}
```

## data_quality

Garmin 字段和接口在不同账号、设备、地区、运动类型下可能不一致。

本项目原则是：

- 字段不确定就返回 `null`
- 接口失败就保留其他可用数据
- 单个字段失败不导致整个 `base` 命令失败
- 失败和缺失写入 `data_quality`

示例：

```json
{
  "data_quality": {
    "connect_splits": {
      "status": "partial",
      "errors": {
        "typed_splits": "..."
      }
    },
    "fit_download": {
      "status": "error",
      "message": "..."
    }
  }
}
```

## HTML 导出

html 模式会生成：

```text
data/exports/html/<run_id>/index.html
data/exports/html/<run_id>/<activity_id>/index.html
data/exports/html/<run_id>/<activity_id>/charts.html
```

full 模式会为每条活动生成：

```text
charts.html
```

第一版包含：

- 心率 + 配速图
- 步频 + 功率图
- 海拔图
- GPS 轨迹图，如果有 GPS 数据
- 每公里 `km_splits` 表

可以直接在浏览器打开：

```text
data/exports/latest/<run_id>/<activity_id>/charts.html
```

也可以打开总入口：

```text
data/exports/latest/<run_id>/index.html
```

## 给 AI 分析时的建议

优先把 `base` JSON 作为上下文：

```bash
uv run garmin-ai base --limit 1 --json
```

分析优先级：

1. `profile`
2. `current_metrics`
3. `recent_runs[].summary`
4. `recent_runs[].day_metrics`
5. `recent_runs[].km_splits`
6. `recent_runs[].fit_laps`
7. `recent_runs[].connect_splits`

只想人工查看时，使用 html 模式：

```bash
uv run garmin-ai base --limit 5 --mode html --output ./data/exports/html
```

只有需要逐秒或逐点分析时，再使用 full 模式导出的文件：

- `records.csv`
- `running_dynamics.csv`
- `gps.csv`

## 常用命令速查

```bash
# 安装依赖
uv sync

# 登录并保存 token
uv run garmin-ai auth

# 最近 1 条跑步，JSON 输出
uv run garmin-ai base

# 最近 5 条跑步
uv run garmin-ai base --limit 5

# 最近 1 条跑步，并返回最近 7 天精简睡眠摘要
uv run garmin-ai base --limit 1 --sleep-days 7 --json

# 保存基础 JSON 到文件
uv run garmin-ai base --limit 1 --output ./data/exports/base_context.json

# 导出基础 CSV/JSON 到目录
uv run garmin-ai base --limit 1 --output ./data/exports/base

# html 模式导出浏览器报告
uv run garmin-ai base --limit 5 --mode html --output ./data/exports/html

# 按时间轴生成 HTML 图表
uv run garmin-ai base --limit 5 --mode html --chart-x time --output ./data/exports/html

# full 模式导出 FIT、CSV、Parquet、HTML
uv run garmin-ai base --limit 1 --mode full --output ./data/exports/latest

# 不使用 FIT 缓存，重新下载
uv run garmin-ai base --limit 1 --no-cache
```

## Git 忽略

以下内容不应提交：

- `.venv/`
- `.env`
- `data/fit/`
- `data/cache/`
- `data/exports/`
- `.garminconnect/`
- `*.fit`
- `*.parquet`

Garmin token 默认在用户目录：

```text
~/.garminconnect
```

它不在项目目录内，也不应提交到 Git。
