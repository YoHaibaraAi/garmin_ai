# Garmin Running Analysis

Use the `garmin-ai` CLI when the user asks about:

- 最近训练
- 最近一次跑步
- 最近 N 条跑步
- 跑步分析
- Garmin 数据
- 睡眠、HRV、恢复、VO2max、静息心率、体重

## Rules

1. 最近训练 / 最近一次跑步：

   ```bash
   garmin-ai base --limit 1 --json
   ```

2. 最近 N 条跑步：

   ```bash
   garmin-ai base --limit N --json
   ```

3. HTML 图表解析 / 可视化详细分析：

   ```bash
   garmin-ai base --limit N --mode html --output <dir>
   ```

   当用户要求“看图表分析”“html 模式”“生成图表”“配速/心率/功率趋势”“详细分析但不需要逐秒原始表”时，优先使用 html 模式。解析顺序：

   - 先打开顶层 `index.html` 确认最近跑步列表和 `Report` / `Charts` 链接。
   - 再打开每条活动目录下的 `charts.html` 观察趋势图。
   - 最后结合该活动的 `index.html`、`context.json`、`summary.json`、`km_splits.csv`、`fit_laps.csv` 和 `connect_splits.json` 做解释。

   html 模式适合人类可读报告和图表分析；它会生成单次活动报告与 `charts.html`，但不应假设存在完整 `records.csv`、`running_dynamics.csv`、`gps.csv`、`records.parquet` 或原始 FIT 文件。
   目录型导出会写入 `<dir>/<run_id>/`，每次运行一个独立目录，并生成同级 `<dir>/<run_id>.zip`；使用返回 JSON 里的 `export_dir` 和 `export_archive` 定位本次文件。

4. 精简低 token 分析：

   ```bash
   garmin-ai base --limit N --mode compact --compact-format html --output <dir>
   garmin-ai base --limit N --mode compact --compact-format json --output <dir>
   ```

   当用户要求“精简模式”“省 token”“只要 summary 和 connect splits”“不要图表”“可以输出 html 或 json”时，优先使用 compact 模式。

   compact HTML 顶层 `index.html` 的 Current Metrics 表和 base HTML 保持一致，并保留睡眠摘要表和最近跑步列表，但去掉睡眠趋势图；单次活动 `index.html` 只保留 Summary 和 Connect Splits。compact JSON 只保留顶层指标、睡眠摘要、跑步 summary 和 Connect Splits。compact 模式不会生成 `charts.html`，也不会下载/解析 FIT。
   目录型 compact 导出同样写入 `<dir>/<run_id>/` 并生成同级 `<dir>/<run_id>.zip`；如果 `--compact-format json --output xxx.json`，则直接写入该 JSON 文件，不生成压缩包。

5. 全量数据 / 逐秒数据 / 跑步动态 / GPS / 原始 FIT：

   ```bash
   garmin-ai base --limit N --full --output <dir>
   ```

   full 模式也会生成 html 报告和 `charts.html`，但主要用于需要底层明细文件的分析。只有用户要求逐秒、跑步动态、GPS、轨迹、原始 FIT、CSV/Parquet 明细或需要复核图表背后的每条记录时，才优先使用 full。

6. 分析优先使用：

   - `profile`
   - `current_metrics`
   - `current_metrics.vo2max`
   - `current_metrics.vo2max_precise`
   - `current_metrics.hrv_7d_avg`
   - `current_metrics.resting_heart_rate_7d_avg`
   - `recent_runs[].summary`
   - `recent_runs[].day_metrics`
   - `recent_runs[].connect_splits`
   - `recent_runs[].fit_laps`
   - `recent_runs[].km_splits`

   `vo2max` 是 Garmin 展示值；`vo2max_precise` 是更精确值，趋势分析时优先参考 `vo2max_precise`。

   `current_metrics.sleep` 默认是最近 7 天精简睡眠摘要，可用 `garmin-ai base --sleep-days N --json` 调整天数。它只包含每天的睡眠分、总睡眠、深睡、浅睡、REM、清醒、入睡/醒来时间和缺失标记，以及区间平均值。

   `recent_runs[].day_metrics.sleep` 是单日精简睡眠摘要。不要期待或读取 Garmin 原始睡眠字段；`base` 不输出 `sleepLevelsMap`、`sleepMovement`、`respiration`、`hrvReadings`、原始 sleep response 或完整 `sleepScores` 对象。如需原始睡眠数据，后续可以新增 `sleep --raw` 命令，但当前版本没有 raw 命令。

   最大心率必须区分三种语义：

   - `profile.max_heart_rate`：个人最大心率设置，优先来自 Garmin 设备/设备设置，其次来自本地配置。
   - `current_metrics.daily_max_heart_rate`：当天全天最高心率。
   - `recent_runs[].summary.max_hr`：某次活动最高心率。

   如果 Garmin 接口拿不到个人最大心率，可提示用户运行：

   ```bash
   garmin-ai config set max-heart-rate 190
   ```

7. 只有用户要求逐秒分析时才读取：

   - `records.csv`
   - `running_dynamics.csv`

8. 除非用户明确要求路线、轨迹、GPS、地图、爬升位置或配速与路线关系，否则不要读取或分析：

   - `gps.csv`

9. 如果返回 `AUTH_REQUIRED`：

   提示用户运行：

   ```bash
   garmin-ai auth
   ```
