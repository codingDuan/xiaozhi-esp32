# D 版摄像头实物门禁

> **下单方向门禁已通过。** 结论来自一期 2 号板断电导通实测与本目录实物摆放照片的交叉核验，
> 不是根据 CAD 图猜测。首板摄像头上电前门禁仍为 PENDING。

## 1:1 打印核验稿

使用本目录的 [CAMERA_1TO1_CHECK_ONLY.pdf](CAMERA_1TO1_CHECK_ONLY.pdf)。打印时选择
**实际大小 / 100%**，关闭“适合页面”“缩小超大页面”等自动缩放。打印后先用尺测量板框直边，
应为 **65×55mm**；尺寸不符时禁止用于核验。

把 AFC01-S24FCA-00 实物座子与摄像头排线放到打印稿左上角的 J_CAM 上，核对定位焊盘、
1 脚圆点、触点朝向和镜头方向。照片必须同时拍到实物、J_CAM 轮廓/1 脚标记以及打印稿板框；
本 PDF 仅用于方向核验，不是 Gerber 或生产文件。

## 下单前（spec §7.3）

ORDER_GATE_STATUS: VERIFIED
CONNECTOR_LCSC: C262669
CAMERA_MODULE: AFC01-S24FCA-00
CONTACTS_DIRECTION: DOWN
CAMERA_PIN_1_PAD: 24
CAMERA_PIN_24_PAD: 1
LENS_DIRECTION: AWAY_FROM_PCB
ORDER_VERIFIED_DATE: 2026-10-05
ORDER_VERIFIED_BY: 委托方实物照片 + 一期 2 号板断电实测记录复核
EVIDENCE_IMAGE: camera_orientation_evidence_2026-10-05.png
EVIDENCE_SHA256: 3a7ccea86a2faeb5b15949b13e0381540d71ee0a99807e8c3d363465cbb038bb

核验目标值为：触点朝下，摄像头 pin 1 落到 J_CAM pad 24、pin 24 落到 pad 1，
镜头朝 PCB 外侧。照片必须同时看清连接器 1 脚标记、排线触点方向和镜头方向。

核验说明：照片中排线印字面朝上，因此金属触点朝下；镜头位于板框外侧；J_CAM 的 1 脚圆点在右端。
一期 2 号板断电导通实测已经证明这种下接触插法会让摄像头第 k 脚落在 PCB 第 25−k 焊盘，
所以二期按反向关系连接：摄像头 pin 1 → PCB pad 24，pin 24 → PCB pad 1。该结论不依赖照片中
无法直接看见的 FPC 铜面脚号。照片只放行下单方向；首板仍须完成下方断电测量后才能给摄像头上电。

## 首板摄像头上电前（spec §7.4）

POWER_GATE_STATUS: PENDING
EMPTY_PIN_TO_1V5: PENDING
DIODE_1V5_TO_GND_WITHOUT_CAMERA:
DIODE_1V5_TO_GND_WITH_CAMERA:
DIODE_1V5_TO_GND_RESULT: PENDING
POWER_VERIFIED_DATE:
POWER_VERIFIED_BY:

断电插入摄像头后，空脚到 +1V5 必须为 OL；+1V5 到 GND 的二极管档读数不得比未插摄像头时明显降低。
