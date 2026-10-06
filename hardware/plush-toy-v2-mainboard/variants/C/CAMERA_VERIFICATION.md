# C 版摄像头实物门禁

> **当前禁止导出生产包。** 下单前必须使用一代 2 号板或 1:1 打印稿配合
> AFC01-S24FCA-00 实物排线完成核验，并把原始照片放在本目录。不要根据 CAD 图猜测后把状态改为 VERIFIED。

## 1:1 打印核验稿

使用本目录的 [CAMERA_1TO1_CHECK_ONLY.pdf](CAMERA_1TO1_CHECK_ONLY.pdf)。打印时选择
**实际大小 / 100%**，关闭“适合页面”“缩小超大页面”等自动缩放。打印后先用尺测量板框直边，
应为 **65×55mm**；尺寸不符时禁止用于核验。

把 AFC01-S24FCA-00 实物座子与摄像头排线放到打印稿左上角的 J_CAM 上，核对定位焊盘、
1 脚圆点、触点朝向和镜头方向。照片必须同时拍到实物、J_CAM 轮廓/1 脚标记以及打印稿板框；
本 PDF 仅用于方向核验，不是 Gerber 或生产文件。

## 下单前（spec §7.3）

ORDER_GATE_STATUS: PENDING
CONNECTOR_LCSC: C262669
CAMERA_MODULE: AFC01-S24FCA-00
CONTACTS_DIRECTION: PENDING
CAMERA_PIN_1_PAD: PENDING
CAMERA_PIN_24_PAD: PENDING
LENS_DIRECTION: PENDING
ORDER_VERIFIED_DATE:
ORDER_VERIFIED_BY:
EVIDENCE_IMAGE:
EVIDENCE_SHA256:

核验目标值为：触点朝下，摄像头 pin 1 落到 J_CAM pad 24、pin 24 落到 pad 1，
镜头朝 PCB 外侧。照片必须同时看清连接器 1 脚标记、排线触点方向和镜头方向。

## 首板摄像头上电前（spec §7.4）

POWER_GATE_STATUS: PENDING
EMPTY_PIN_TO_1V5: PENDING
DIODE_1V5_TO_GND_WITHOUT_CAMERA:
DIODE_1V5_TO_GND_WITH_CAMERA:
DIODE_1V5_TO_GND_RESULT: PENDING
POWER_VERIFIED_DATE:
POWER_VERIFIED_BY:

断电插入摄像头后，空脚到 +1V5 必须为 OL；+1V5 到 GND 的二极管档读数不得比未插摄像头时明显降低。
