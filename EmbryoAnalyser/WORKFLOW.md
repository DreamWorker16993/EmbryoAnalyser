# Embryo analysis workflow

统一入口是 `run_workflow.ipynb`，也可直接使用 `workflow.py`。分类与邻居统计可以分别运行。

```text
measurement CSV（一个文件 = 一个胚胎）
  → AR > 1.5 清理 → 相关特征筛选 → 每特征 16 bins 的细胞百分比
  → RF / SVM 训练并保存 → 单个 / 批量 CSV 预测 → CSV + JSON 报告

fixed embryo TIFF + ROI ZIP
  → 复制到 outputs 中独立工作目录
  → 独立 Fiji GUI 进程运行原邻居计数宏的工作副本
  → slow_neighbour_counting.csv → Python 百分比分布图 + 频数表 + 汇总
```

## Notebook 使用

打开 `run_workflow.ipynb`，选择本目录 `.venv/Scripts/python.exe` 作为 Python 环境，从头运行。输入配置单元中的 `CSV_INPUTS` 和 `IMAGE_INPUTS` 都支持单文件、多文件列表或目录（递归）。图片自动查找同目录的 `<图片名>_rois.zip`；只有一个 ZIP 时也可自动匹配。已有 ROI 是当前流程的前提。

`RUN_CLASSIFICATION`、`RUN_FIJI` 决定运行哪些分支；`RETRAIN` 决定重新训练还是加载已保存的模型。结果表和分布图会在 notebook 中展示，也会保存到项目根目录 `outputs/notebook/`。默认图片为一个较小的测试样本，批量处理时更改 `IMAGE_INPUTS` 即可。

本次已建立独立分析环境并通过验证。重新安装环境时，在项目根目录运行以下命令；依赖锁文件记录了本次验证的版本，不会改动原 Fiji 环境。

```powershell
& '.\fiji-agent\.venv\Scripts\python.exe' -m venv '.\EmbryoAnalyser\.venv'
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' -m pip install -r '.\EmbryoAnalyser\requirements.lock.txt'
```

不需要修改全局 Python、PATH 或用户 Jupyter 配置。在已有 notebook 编辑器中直接选择上述环境。邻居统计另外复用现有 `fiji-agent/.venv` 和 `C:\Users\ethan\Desktop\Fiji`。

## 命令入口

在项目根目录使用 PowerShell。默认训练输入仅为 `gap43-mCherry/train`，不会自动读取其 `test` 子目录。

```powershell
# 训练两种模型；只使用 RF 或 SVM 时改为 --model rf 或 --model svm
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' train --model both --output '.\outputs\training'

# 单个 CSV 预测
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' classify --input '.\dataset\raw_dataset\E-CadGFP\control\6-22-EM1\measurement.csv' --model-file '.\outputs\training\models.joblib' --output '.\outputs\single_csv'

# 目录内所有 CSV 批量预测；--input 后也可指定多个独立 CSV
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' classify --input '.\dataset\raw_dataset\E-CadGFP' --model-file '.\outputs\training\models.joblib' --output '.\outputs\batch_csv'

# 单张图片：复制 TIFF + ROI，真实运行 Fiji，再输出 Python 图表
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' neighbours --input '.\dataset\fixed_EM\processed\del15\s9_1\Composite.tif' --output '.\outputs\single_image'

# 批量图片：递归目录输入；--input 后也可指定多个图片路径
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' neighbours --input '.\dataset\fixed_EM\processed\del15' --output '.\outputs\batch_images' --timeout 3600

# 已有计数 CSV 可直接绘图，目录输入只选 slow_neighbour_counting.csv
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' '.\EmbryoAnalyser\workflow.py' distribution --input '.\dataset\fixed_EM\processed\del15' --output '.\outputs\distributions'
```

`neighbours` 会打开独立的 Fiji 界面，完成后退出该进程。原宏的 `close("*")` 仅作用于此独立进程。`--show` 可显示已保存的 Python 图表；notebook 会直接展示 PNG 和返回的 figure。不同 Fiji 安装可指定 `--fiji-path`；兼容的 PyImageJ 环境可指定 `--fiji-python`。`--timeout` 的单位为秒，覆盖整个图片批次；默认不设固定时间上限，避免大批次被中断。需要限制运行时间时可显式设置。

## 输出

| 分支 | 输出文件 |
|---|---|
| 训练 | `models.joblib`、`training_profiles.csv`、`training_report.json` |
| 预测 | `predictions.csv`、`profiles.csv`、`classification_report.json` |
| 图片邻居统计 | 唯一运行目录中的输入副本、工作宏、`slow_neighbour_counting.csv`、`neighbour_distribution.csv`、PNG、PDF，以及 `neighbour_summary.csv`、JSON 报告和 Fiji 日志 |
| 已有计数绘图 | 每个输入独立目录中的频数 CSV、PNG、PDF，及 `distribution_summary.csv` |

预测表每个输入文件对应一行：`source_csv`、总细胞数、保留细胞数、所选模型的预测和文本标签。`0=control`、`1=mutant`。预测无需真实标签；只有文件名或目录名为 `control`/`mutant`，或目录以前缀 `control-`/`mutant-` 命名时才输出 `true_label` 并计算 accuracy / macro F1。报告另外列出同时出现在训练输入中的文件。模型保存了相关筛选、分箱边界、重要特征列及 SVM scaler；预测时不会重算这些状态。

## 与原代码的关系

原 `final_analyser.ipynb`、`n_neighbour_distribution.ipynb`、`neighbour_counting_connect_centroid.ijm` 均保留。

- `preprocessing.py` 复制并封装 final notebook 的 cells 2–3、10、13–14、23–24（0 起始编号）。角度修正用于相关性计算，分箱仍使用原测量值。保留 AR 阈值 1.5、相关阈值 0.75、16 bins。
- `classifiers.py` 复制 cells 28–41 的 RF、LinearSVC 参数及重要性筛选后的重训。原实际筛选规则为重要性至少 5%。
- `neighbours.py` 复制 `n_neighbour_distribution.ipynb` 的百分比 histogram；额外支持单图、保存频数及超过 9 的邻居数量。Fiji 工作宏只替换目录选择语句，其余计数代码与原文件一致。
- 新入口将训练和预测分开，预处理只从明确指定的训练 CSV 拟合。原 notebook 的全数据预处理和提前 scaling 的 LeaveOneOut 分数不作为新流程验证分数。跨 strain 分类表现应通过输出报告评估；本次目标是复用并串联已有算法。

CSV 缺少必需测量列、没有 `AR > 1.5` 的细胞或某特征所有值都超出训练 bins 时会明确报错。部分超范围值沿用原 `pd.cut` 行为，不计入该特征百分比的分母。训练需要包含 control 和 mutant 两类胚胎；任意命名的训练 CSV 可通过 Python API 的 `labels=[0, 1, ...]` 参数提供标签。

所有写入入口都会拒绝 `dataset` 内的路径，包括指向它的目录链接。测试使用临时目录及 `outputs`，不会更新、覆盖或删除输入文件。

## 验证

```powershell
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' -m pip check
& '.\EmbryoAnalyser\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
```

测试覆盖原 notebook 算法回归、单个/批量 CSV、两种及单独模型、保存恢复、输入异常、分布频数与 PNG/PDF、CLI 和 dataset 写入保护。真实 Fiji 单图和两图批量运行另有验证报告，保存在 `outputs/fiji_validation/`；完整 workflow 示例输出保存在 `outputs/workflow_validation/`。
