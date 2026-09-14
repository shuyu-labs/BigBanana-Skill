# 项目 schema 与状态

项目脚本使用 `schema_version: 2`。角色、场景、道具、镜头和衣橱都有稳定 `id`。

```json
{
  "schema_version": 2,
  "characters": [{"id": "char_x", "name": "..."}],
  "scenes": [{"id": "scene_x", "name": "..."}],
  "props": [{"id": "prop_x", "name": "..."}],
  "wardrobe": [{"id": "wardrobe_x", "character_id": "char_x"}],
  "shots": [{
    "id": "shot_x", "shot_id": "S01",
    "character_ids": ["char_x"], "scene_id": "scene_x", "prop_ids": ["prop_x"]
  }]
}
```

`manifest.json` 保存模型、输入哈希、资源路径、镜头状态和更新时间。恢复时先复用非空产物，再只执行缺失步骤。资产文件按 `character_01_*.png`、`scene_01_*.png`、`prop_01_*.png` 命名，引用解析优先使用实体 ID。

修改角色或场景后，应重新生成受影响的首帧；已有视频不能假定仍然连续。旧版仅含名称的脚本通过 `bigbanana_project.normalize_script` 自动补 ID。
