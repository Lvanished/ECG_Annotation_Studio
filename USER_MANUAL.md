# ECG Annotation Studio 使用手册

本手册按界面上实际出现的控件编写。按钮名称保留英文，与屏幕上的文字一致。

这是研究原型，不是医疗器械。状态栏右侧固定显示：`research prototype, not a medical device`。自动标注只是待人工确认的建议。

启动后打开 http://localhost:5173（若改过 `.env` 里的 `FRONTEND_PORT`，用那个端口）。

## 界面分区

打开一条记录后，窗口分成五块：

| 位置 | 内容 |
|---|---|
| 顶栏 | 数据集、记录、导联、工具、缩放、保存、自动标注、导出 |
| 中部 | 波形画布，以及画布上方的范围 / 读数条 |
| 波形下方 | 时间轴、各标注层级、预测层、整段概览条 |
| 右侧 | 记录信息、标注属性或预测审核、预测运行列表、快捷键 |
| 底部 | Measurements、Signal quality、Validation、History |

波形与层级之间、层级与底栏之间、主区与右侧之间各有一条浅灰色分隔条。鼠标变成调整大小的光标后拖动，即可改变对应区域的高度或宽度。

底部状态栏显示最近一次操作的结果。成功为绿底，失败为红底。未保存的修改在切换记录时会询问 `Discard unsaved annotation changes?`；关闭或刷新页面前，浏览器也会提示有未保存内容。

在输入框、下拉框里打字时，除 `Ctrl+S` 外，快捷键不生效。

## 还没有打开记录时

顶栏只有标题、数据集下拉框和记录下拉框。主区是一张表：

| 列 | 含义 |
|---|---|
| dataset | 数据库名称和版本 |
| license | 数据许可 |
| local WFDB records | `data/physionet` 里已有、尚未登记的记录数 |
| registered | 已经导入、可以在记录下拉框里选择的条数 |

有记录时，标题是 **Select a recording in the toolbar**。没有记录时，标题是 **No recordings registered yet**。

**Register local PhysioNet records (data/physionet)**  
把本机 `data/physionet` 里的 LUDB、QTDB、MIT-BIH 记录登记进数据库。进行中按钮变为 **Importing…**。Docker 默认启动时已经自动登记过自带的 10 条，一般不用再点。

表下方的说明指向下载更多记录的命令，那些文件会按 PhysioNet 公布的 SHA-256 校验。

## 顶栏

从左到右。未打开记录时，**Leads** 及之后的控件不显示。

### 选择数据

| 控件 | 作用 |
|---|---|
| 数据集下拉框（默认 **All datasets**） | 只列出已有记录的数据库，例如 `LUDB (8)`。选中后，记录列表只显示该库。 |
| 记录下拉框（默认 **Select recording…**） | 选项格式：`数据集/记录名 · 导联数L · 采样率Hz · 时长s`。选中后加载波形和标注，地址栏加上 `?recording=`。刷新页面会重新打开同一条。选回空项会关闭当前记录。 |

加载成功时状态栏类似：`Loaded ludb/3: 5000 samples @ 500 Hz, 12 leads, 601 annotations`。

### 导联

**Leads: all N ▾**（或 **Leads: I,II,… ▾**）  
打开导联菜单。鼠标移出菜单后关闭。

| 菜单项 | 作用 |
|---|---|
| **All** | 显示该记录的全部导联。 |
| **Single** | 只显示当前标注导联；若未指定，则显示第一条导联。 |
| 每条导联的复选框 | 单独显示或隐藏。至少保留一条，不能把最后一条也取消。 |

**Annot. lead**  
新标注写到哪一条导联上。层级里显示「这条导联的标注」加上「不绑定导联的全局标注」。选某一条时，若它当前没显示，会自动加进波形。最后一项 **(all / global)** 表示新标注不绑定导联。

波形左侧每条导联的名称本身也是按钮，点击即把它设为标注导联。当前标注导联的名称条左侧有蓝边。名称右侧是单位（mV）和一条 **1 mV** 标尺。

**N mV/strip**（1、1.5、2、2.5、3、5、8、12）  
每条导联条带所代表的幅度。数值越小，波形看起来越高。

### 工具和标签

| 控件 | 作用 |
|---|---|
| **Select** | 选择工具。快捷键 `V`。在波形上拖拽得到时间选区，单击设置光标；靠近点标注时会选中它。 |
| **Annotate** | 标注工具。快捷键 `A`。在波形上单击，若当前层级接受点，则新建一个点；拖拽，若当前层级接受区间，则新建一个区间。拖拽出的选区在选择工具下只作为选区，不立刻建标注。 |
| 层级下拉框 | 当前活动层级，新建标注写到这里。 |
| 标签下拉框 | 新建标注使用的标签，只列出该层级、该几何类型允许的标签。 |
| 自由文本框（占位符 **label (free text)**） | 仅自定义层级出现，可输入任意标签；下拉建议仍是本体里对该层级合法的标签。 |
| **+ Tier** | 打开 **New custom tier** 对话框。 |

### 视图

| 控件 | 作用 |
|---|---|
| **＋** | 以视图中心放大。快捷键 `+` 或 `=`。 |
| **－** | 以视图中心缩小。快捷键 `-`。 |
| **Fit** | 显示整条记录 `[0, 总采样点数)`。快捷键 `F`。 |
| **Fit sel.** | 把视图缩到当前选区。没有选区时按钮不可用。快捷键 `Z`（同样要求已有选区）。 |
| **◀ beat** | 跳到上一个心搏并居中。快捷键 `[`。 |
| **beat ▶** | 跳到下一个心搏并居中。快捷键 `]`。 |
| **start** / **end** / **Go** | 输入采样点后跳到半开区间 `[start, end)`。`end` 必须大于 `start`。 |

找不到心搏时，状态栏写 `No beats: add R_peak/Beat annotations or run R-peak detection`，或 `No further beat in that direction`。心搏按当前标注导联上的 R 峰（没有则用心搏点，再没有则用 QRS 中点）定位。

### 编辑和保存

| 控件 | 作用 |
|---|---|
| **↶ Undo** | 撤销一步。没有可撤销操作时不可用。快捷键 `Ctrl+Z`。一次拖拽算一步。 |
| **↷ Redo** | 重做。快捷键 `Ctrl+Shift+Z` 或 `Ctrl+Y`。撤销之后若又做了新编辑，重做记录被清空。 |
| **Save** | 把全部未保存修改一次写入。有修改时显示 **Save (N)** 并高亮，`N` 是与服务器不一致的标注条数。快捷键 `Ctrl+S`。 |
| **Auto-annotate ▾** | 打开自动标注菜单。运行中按钮变为 **Running…** 且不可再点。 |
| **Export / Import** | 打开导出与导入对话框。 |

保存成功时状态栏类似 `Saved: 3 created, 0 updated, 0 deleted`。失败时整批都不会写入，例如重叠、标签不被该层级允许，或别人（或另一个标签页）已经改过同一条（版本冲突）。

修改 **reviewed** 状态的标注时会先弹出确认。取消则状态栏为保存已取消，该条保持原样。

### Auto-annotate 菜单

鼠标移出菜单后关闭。检测和勾边使用 **Annot. lead**；若选的是全局，则用当前显示的第一条导联。检测窗口至少 2 秒，否则状态栏报错。

| 控件 | 作用 |
|---|---|
| **SciPy Pan-Tompkins (adaptive)** / **WFDB XQRS** | 选择 R 峰算法。短记录（约 10 秒的 LUDB）用 Pan-Tompkins 更合适，XQRS 需要更长的学习段。 |
| **Detect in view** | 只在当前可见范围内检测 R 峰。 |
| **Whole recording** | 对整条记录检测 R 峰。 |
| **Segment beats from latest R-peak run** | 用最近一次 Pan-Tompkins 或 XQRS 的结果切心搏区间。没有这样的运行时，改用已有的 R 峰或心搏点标注。至少需要两个峰。 |
| **Delineate in view** | 在当前可见范围内做 P、QRS、T 勾边。菜单标明 **P/QRS/T delineation — experimental**，并写明 *Heuristic search; not clinically validated. Review every boundary.* |

完成后状态栏类似 `scipy_pan_tompkins@1.1.0: 9 predictions on II - review in the prediction layer`。勾边还会带 `(EXPERIMENTAL)`。这些结果出现在预测层，还不是正式标注。

## 波形区

画布上方一条读数，从左到右：

- `view [起点, 终点) · 起止时间 · span N ms`：当前可见的半开采样区间。
- `mouse sample N · 时间 · 导联 电压`：鼠标在画布上时，显示鼠标所在采样点；离开后改为 `cursor sample`。电压是 `x.xxx mV`；若当前是包络而不是原始点，则是 `[最小, 最大] mV`。最多列出前三条显示中的导联。没有光标时显示 `no cursor`。
- `selection [a, b) = N ms`：仅在有选区时出现。
- 最右侧：`raw samples`（原始点）或 `min/max envelope · N samples/bucket`（每段的最小/最大值，窄的 QRS 不会被平均掉）。数据还在加载时附加 `· loading…`。

画布上的操作：

| 操作 | 结果 |
|---|---|
| 滚轮 | 以鼠标所在采样点为锚缩放。 |
| `Shift`+滚轮，或触控板横向滑动 | 平移。 |
| 中键拖动 | 平移。 |
| 左键拖动（Annotate，且层级接受区间） | 新建区间，范围是拖过的采样点。 |
| 左键拖动（Select） | 设置选区，并把光标放在起点。 |
| 左键单击（Annotate，且层级接受点） | 在该采样点新建点标注。 |
| 左键单击（Select） | 设置光标；若附近 6 像素内有点标注，则选中它。 |
| `Esc` | 清除选区，并取消当前选中的标注。 |

网格在放得足够大时按心电图纸的 40 ms / 200 ms 画。全局标注（不绑定导联）在波形上画成细带，不会染满整幅图。

## 层级区

层级按本体顺序排列。每行左侧是名称条，右侧是与波形对齐的时间轨道。

名称条上的控件：

| 控件 | 作用 |
|---|---|
| **▾** / **▸** | 展开或折叠该行。折叠后只剩一条细行。 |
| 层级名（前面的数字 1–9） | 设为活动层级。名称后的符号：`•` 点，`▭` 区间，`•▭` 两者都接受。悬停可看到类型、作用范围、重叠规则和对应数字键。 |
| **✕** | 隐藏该层级。隐藏后不在列表里画，也不占用数字键。轨道下方出现 **Hidden tiers:**，每个名称后带 **↺**，点击重新显示。 |

轨道上的操作：

| 操作 | 结果 |
|---|---|
| 单击空白处 | 把该层级设为活动层级，并把光标移到点击的采样点。 |
| 双击空白处 | 若该层级接受点，则在该采样点新建点标注；若只接受区间，状态栏提示改为在波形上拖拽，或先选范围再按 `Enter`。 |
| 拖点标记 | 左右移动该点，按整采样点吸附。 |
| 拖区间中间 | 整体平移，长度不变。 |
| 拖区间左/右边缘（约 6 像素） | 只改起点或终点，并保持起点小于终点。 |

拖完若会与同层级、同导联上已有区间重叠，移动被退回，状态栏写 `Move rejected: would overlap …`。悬停标注可看到标签、采样点、导联、来源（manual / reference / algorithm / imported）和审核状态。

选中的标注带琥珀色框。时间轴上的红线是光标所在采样点。

**Predictions (N pending)**  
橙色斜纹行，只画状态为 pending 的预测。点是虚线，区间是虚线框。点可以在这一行里左右拖，表示审核时改过位置；区间在这里不能拖。单击一条预测后，右侧变为 **Prediction review**。一次最多画当前视图里的 600 条。

最底部细条左侧是记录总时长，右侧是整段概览。蓝色块表示当前视图在整条记录中的位置。在这条上单击或拖动，视图会跳到对应位置并保持当前宽度。

## 右侧面板

标题随选中对象变化：**Recording**、**Annotation properties** 或 **Prediction review**。

### Recording（未选中标注或预测时）

显示记录名、采样率、采样点数、时长、导联列表、存储单位和原始单位、病人/分组编号。LUDB 还会显示年龄、性别、头信息里的节律和诊断。下面是信号文件 SHA-256 的前 16 位、数据库全名、版本、许可证、标注含义、来源链接，以及 **Cite:** 开头的引用（使用这些数据发表结果时需要引用）。

### Annotation properties

点层级里的一条标注后出现。

| 控件 | 作用 |
|---|---|
| 顶行 `new (unsaved)` 或 `id …`，以及 `rev N` | 未保存的新标注还没有服务器编号。`● modified` 表示相对上次保存有改动。 |
| **Tier** | 改层级。只列出能接受这种几何（点或区间）的层级。 |
| **Lead** | 改导联，或选 **global (all leads)**。 |
| **Label** | 改标签。自定义层级是文本框，失焦或按 `Enter` 后生效。 |
| **Sample** 或 **Start sample** / **End sample (excl.)** | 直接改采样点。失焦或 `Enter` 后生效；不合法的输入会恢复原值。终点是半开区间的右端，不包含该采样点。 |
| 时间与 duration | 由采样点和采样率算出，只读。 |
| **note**、**uncertain**，以及 **morphology** 等 | 由标签决定。枚举是下拉框，布尔是复选框，文本失焦后写入。清空表示删除该属性。 |
| **x_key**、**value**、**+** | 增加自定义属性。名称会自动加上 `x_` 前缀。已有自定义属性右侧的 **✕** 删除它。 |
| **Review status** | `draft`、`needs_review`、`reviewed`、`rejected`。标成 `reviewed` 之后，再次修改或删除都要确认。 |
| source / ontology / beat_id | 只读。**provenance** 可展开，看到这条标注来自哪个数据文件或哪次算法。 |
| **Delete annotation (Del)** | 删除当前标注。快捷键 `Delete` 或 `Backspace` 相同。 |
| **Revision history** | 已保存标注的每次创建、修改、删除：版本号、操作、当时的标签和范围、操作者、时间。 |

这些修改都先留在本地，要点 **Save** 才写入。导入的参考标注来源是 `reference`，审核状态是 `reviewed`。

### Prediction review

在预测层点一条预测后出现。

显示标签、导联、点或区间、采样点、状态，以及算法名、版本。实验性算法标 **EXPERIMENTAL**。**parameters** 可展开查看当时的参数。

仅当状态为 pending：

| 控件 | 作用 |
|---|---|
| **Modify sample** | 只对点预测出现。改采样点；与原位置相同则视为没改。也可以直接拖预测层里的虚线。 |
| **Accept** 或 **Accept modified** | 变成正式标注，来源为 algorithm，并记下原采样点和算法。若你移动过，按钮是 **Accept modified**。与已有同类标注重叠，或与已审核标注重叠时，接受失败，状态栏以 `Accept failed` 开头，已审核标注不会被覆盖。 |
| **Reject** | 拒绝这条预测，不再显示。状态栏：`Prediction rejected`。 |

接受或拒绝都是立刻生效，不需要再点 **Save**。

### Prediction runs

每次自动标注产生一条运行记录：算法、版本、是否 **experimental**、导联、采样范围，以及 pending / accepted / modified / rejected 的数量。

| 按钮 | 作用 |
|---|---|
| **Accept all in selection** | 当前有选区时出现。接受起点落在选区内的全部 pending 预测。冲突的跳过并在状态栏报告数量。 |
| **Accept all in view** | 没有选区时出现。范围改为当前可见区间。 |
| **Discard run** | 删除这次运行及其尚未接受的预测。已经接受并变成标注的条目保留。 |

### Keyboard shortcuts

右侧最下方可展开，内容与下表相同。

| 按键 | 作用 |
|---|---|
| `Ctrl+S` | 保存（一次原子写入） |
| `Ctrl+Z` / `Ctrl+Shift+Z`、`Ctrl+Y` | 撤销 / 重做 |
| `Del` | 删除选中标注 |
| `+` / `−`，滚轮 | 以光标或鼠标位置缩放 |
| `Shift+滚轮`，中键拖动 | 平移 |
| `[` / `]` | 上一 / 下一心搏 |
| `←` / `→`（按住 `Shift` 为 10 个采样点） | 移动光标；光标离开可见范围时视图跟随 |
| `Alt+←` / `Alt+→`（`Shift` 为 10 个采样点） | 平移选中的标注；区间长度不变 |
| `Enter` | 在活动层级上，用当前选区建区间，或用光标建点 |
| `A` / `V` | 标注工具 / 选择工具 |
| `F` / `Z` | 整条记录 / 缩放到选区 |
| `1`–`9` | 激活对应的未隐藏层级 |
| `Esc` | 取消选区和当前选中 |

## 底部四个页

点页签名切换。四个页分别是 **measurements**、**signal quality**、**validation**、**history**。

### measurements

用当前视图附近的标注（含未保存修改）计算，导联是 **Annot. lead**。表头写明心搏锚点类型（R 峰、心搏点或 QRS 中点）和采样点，以及是靠近光标还是靠近视图中心。

每一行是一项测量：名称、数值、来源采样点、计算方法。带 **exp** 的是实验性算法（基线、R 波幅度、QRS 峰值幅度、ST 偏移、T 波幅度），不要当成临床测量。缺数据时数值为 **N/A**，来源列写原因，例如 `missing T wave end`，不会填一个估计值。

没有锚点时显示：`N/A — no beat anchors …`。

右侧 **Window summary** 是当前窗口内心搏的个数、中位数、均值和标准差。

### signal quality

当前可见窗口、当前显示导联的描述指标。页首说明：*Descriptive indicators for the visible window; flag thresholds are heuristic and not validated.*

列：amplitude range mv、flatline fraction、clipping fraction、baseline wander ratio、high frequency noise ratio、powerline ratio，以及 flags。数字保留三位小数。

### validation

检查已保存标注是否符合本体，以及父子标注是否包含得当。标题是 `N issue(s) in saved annotations (ontology + parent/child containment)`。点击一条问题会选中对应标注并把视图移过去。只统计已保存的标注，未保存的修改不在这里。

### history

这条记录最近的保存记录（最多 200 条，新的在前）：时间、操作（create / update / delete）、版本、标签、采样范围、操作者。手工保存的操作者是 `local-user`，接受预测产生的是 `prediction-review`。

## 对话框

### New custom tier（**+ Tier**）

点对话框外的暗处或 **Cancel** 关闭。

| 控件 | 选项 |
|---|---|
| **Tier name** | 必填，不能与已有层级重名。 |
| 类型 | **interval**、**point**、**mixed**（点和区间都允许）。 |
| 范围 | **lead-specific** 或 **global (all leads)**。 |
| 重叠 | **overlaps allowed**、**no overlap within a lead**、**no overlap of same label**。 |
| 颜色 | 色块。 |
| **Create** | 创建后该层级立刻成为活动层级，并允许自由文本标签。状态栏：`Created tier "…" (free-text labels allowed)`。 |

说明文字：严格的标签校验需要通过接口 `POST /ontology/labels` 添加本体标签；界面上没有对应按钮。

### Export / Import

标题：**Dataset export (immutable snapshot) & round-trip import**。**Close** 或点暗处关闭。导出只包含已经保存的标注；有未保存修改时，左侧会提示 *You have unsaved edits — exports include saved annotations only.*

左侧 **New snapshot**：

| 控件 | 作用 |
|---|---|
| **Name** | 数据包名称，默认 `ecg-dataset`。 |
| **Version** | 可留空，占位符为 **auto (name-vN)**。同名版本已存在时不能覆盖。 |
| **Scope** | **Current recording**、**Current dataset**、**All recordings**。 |
| **Sources** | `manual`、`reference`、`algorithm`、`imported`。取消勾选的来源不导出。默认全选。 |
| **Review** | `draft`、`needs_review`、`reviewed`、`rejected`。默认不含 `rejected`。 |
| **Mask tiers** | 为哪些区间层级生成逐采样点分割掩码。默认 P Wave、QRS Complex、T Wave。点层级不会出现在这里。 |
| **Split** 的 train / val / test 和 **seed** | 按病人分组划分训练、验证、测试，默认 0.7 / 0.15 / 0.15，种子 42。同一个人不会同时出现在两个集合里。 |
| **Create snapshot** | 生成数据包。按钮在进行中变为 **Working…**。 |

成功后绿框显示版本号、本体版本、标注数、记录数、`patient leakage check` 和 sha256，以及 **Download ZIP**。

右侧 **Import snapshot (round-trip validation)**：

| 控件 | 作用 |
|---|---|
| **Import into new recording(s)** | 导入成新记录，不改原来的记录。 |
| **Verify against database (no writes)** | 只和数据库比对，不写入。 |
| 文件选择（`.zip` 或 `.json`） | 选中后立即开始。 |

结果为 **Round trip OK: sample positions and labels identical** 或 **Differences found**。新记录旁边有 **open …**，点击后打开该记录并关闭对话框。

**Existing snapshots** 列出已有数据包：版本、时间、标注数、**ZIP**（下载）、**Verify**（复查文件是否被改过，以及导出之后数据库里有多少条标注变了）。结果写在左侧红/绿提示里。数据包一旦生成就不能在界面里删除或覆盖。
