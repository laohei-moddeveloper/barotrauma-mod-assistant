# 封面制作记录

方式：插画使用内置 imagegen 生成及编辑；未使用图片生成 CLI。下方首先保留旧中文封面的制作记录，英文动态封面记录见后半部分。

最终提示词要点：原创二次元成年潜艇维修员，银蓝短发、青色眼睛、耳麦、实用深蓝工装与手套，在深海潜艇控制室拿着显示模块、下载箭头和勾选状态的管理平板。深蓝与青色光效，少量琥珀警示灯，窗外是冰冷海底与潜艇轮廓；画面清晰、专业、有吸引力，正方形封面，不采用现有角色或官方标志。

手部修订：人物改为面向镜头的自然三分之四姿态。人物自己的右手在观众左侧持平板，人物自己的左手在观众右侧扶腰。恰好两条手臂，一只左手、一只右手，拇指和手腕方向正确，各自连续连接到自己的手臂、肘部和肩部；移除指向平板的重复手，平板只有一只手接触。

最终版排字编辑仅调整左上图文布局，人物、手部和场景保持原样。第二行“模组助手”缩小约 20% 并左移，副标题放在较窄的青色边框内，文字不得被人物头发遮挡。所有文字必须完整清晰：

- 潜渊症
- 模组助手
- 并行更新 · 智能排序
- 独立工具 · v0.5.0

旧中文原图为 1254×1254，保留在 `assets/cover-final.png`。

## 英文动态封面（2026-10-03）

使用内置 imagegen 对已经认可的中文封面做两次编辑。人物和构图沿用旧封面，移除版本号，所有文字改为英文。第二帧只要求增强灯光，不改变姿势或添加手臂。两张编辑结果经目视检查后保存为 `assets/cover-en.png` 和 `assets/cover-en-bright.png`。

`tools/encode_workshop_cover.py` 使用 Pillow 将生成结果转换格式、缩小至 800×800、统一 GIF 调色板并编码两帧，各显示 1100 毫秒，无限循环。脚本不绘制光效、不合成额外内容。GIF 小于 900000 字节；静态 JPEG 保留原图尺寸，作为订阅包的兼容图。

### 英文常亮帧完整提示词

Use case: text-localization. Edit target: the supplied square Steam Workshop cover for Barotrauma Mod Assistant. Preserve the approved anime illustration EXACTLY: adult silver-blue short-haired submarine mechanic, teal eyes and headset, face, pose, practical dark-blue clothes, deep-sea submarine control-room backdrop, tablet held by her anatomically correct RIGHT hand on the viewer's LEFT, her LEFT hand on viewer's RIGHT resting on her hip. Exactly two arms and two hands, no extra hands, no new objects. Keep the framing and visual quality. Replace ALL Chinese text and the old version number with crisp readable ENGLISH lettering. Top left text: 'BAROTRAUMA' on one line with smaller condensed bold distressed white/cyan sci-fi type fitting comfortably above a large two-line title 'MOD' then 'ASSISTANT'. Maintain ample room around her face. The middle-left narrow outlined panel reads 'PARALLEL UPDATES' then 'SMART LOAD ORDER' in two readable lines. The bottom-left outlined badge reads 'STANDALONE TOOL'. No version number. No other text or Chinese anywhere. Teal monitor and tablet lights are gently luminous in this first animation keyframe; orange room lights softly glow. Do not redraw her body, hands, tablet UI or background details unnecessarily. Produce ONE square finished cover image, not a grid or multiple panels.

### 灯光增强帧完整提示词

Use case: lighting-weather. This supplied English Barotrauma Mod Assistant cover is the edit TARGET and the first animation keyframe. Make ONLY a very subtle second illumination keyframe for a looping GIF. Keep the image pixel-aligned: same square dimensions, camera, all edges, letters, face, hair, anatomy, both hands, headset, clothing, tablet, all UI glyphs, silhouettes and background geometry EXACTLY unchanged. Keep all English lettering EXACTLY unchanged: BAROTRAUMA / MOD / ASSISTANT / PARALLEL UPDATES / SMART LOAD ORDER / STANDALONE TOOL. Only strengthen cyan emissive highlights in the tablet screen check marks and download icon, cyan screen borders, and in the outlined feature panel and bottom badge, and make tiny orange lamp glows a little brighter. Gentle cyan glow pulse, not overexposure or a global brightness change. NO new objects, no motion, no character redraw, no change in the text shape, no new text, no Chinese, no cropping, no camera move. The bright state must preserve readability. Produce one square cover frame, not a contact sheet.

生成工具：内置 imagegen。编码工具：Pillow。最终主封面：`cover-en.gif`。英文静态兼容图：`cover.jpg`。Steam 主预览支持格式的依据：[SetItemPreview](https://partner.steamgames.com/doc/api/ISteamUGC#SetItemPreview)。实际发布后已下载 Steam 返回的预览文件，确认其 MIME 为 image/gif、两帧、无限循环，字节与上传文件一致。封面在两个语言页面共用，标题与简介仍单独本地化。
