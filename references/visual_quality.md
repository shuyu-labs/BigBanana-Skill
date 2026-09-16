# 视觉质量流程

## 九宫格（单图网格协议）

九宫格是**一张图**：一次图像调用生成含全部格子的 storyboard contact sheet，不是逐格生成 9 张图。

1. `grid-prompts` 先用文本模型把一个镜头动作拆成 N 个不重复视角（N=4/6/9；panel 含 index、shot_size、camera_angle、英文 description 10-30 词；shot_size+camera_angle 组合不重复、≥3 种景别；index=0 建立场景、最后一格动作结果）。解析不合格自动纠偏重试一次。
2. `bigbanana_visual.py grid` 用图像模型**一次生成一张** `grid.png`：prompt 固定布局（如 exactly 3 rows x 3 columns、thin white separators、等格不可跨格）+ 逐格描述 + 负向约束（wrong panel counts / merged panels / masonry collage）+ 绝对无文字规则；角色/场景/道具参考图作为连续性锚点传入（--ref）。
3. 人工选定格子后用 `grid-crop --panels <index...>` 从网格图**本地裁切**（PIL，按行列定位，6 格竖图自动推断 3x2 方向），裁出的单格作为首帧参考或首帧提示词的构图依据。
4. 将选中格的构图描述并入首帧提示词，再生成 `s01_start.png`。

九宫格是构图规划素材，不应直接作为视频输入或最终画面（整张贴图除外，可按需直接用作首帧）。

## 衣橱

衣橱变体必须继承角色脸型、发型和体态，只改变剧情需要的服装、配件和磨损状态。生成衣橱参考图时，角色定妆照放在第一张参考图，并把结果路径写回对应 `wardrobe` 项。

## 自动视觉检查

`bigbanana_quality.py` 检查：

- 图片能否解码；
- 宽高是否至少为 `256×256`；
- 像素方差是否过低（纯色/空图）；
- 首帧和角色参考图的感知哈希与颜色分布相似度。

相似度是低成本筛选器，不是身份识别模型。低分应进入人工复核或重新生成，不应自动判定为内容失败。
