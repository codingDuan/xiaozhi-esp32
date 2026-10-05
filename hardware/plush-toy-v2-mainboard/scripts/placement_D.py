"""版本 D 布局（摄像头、双面）。

先复用 C 已验证的 65×55mm 板框、连接器边缘与摄像头方向；
正面只保留 ESP32 模组、模组本地去耦、全部卧式连接器和按键，
其余装配件全部翻到背面。这个尺寸先保证制造可行与布线收敛，不以牺牲连接器丝印或净距追求估算尺寸。
"""

from placement_C import *  # noqa: F401,F403 - D 有意共享 C 的板框与定点几何

# 翻面后让 MPR121 的 GND pad4 朝空旷一侧，避免被相邻密脚封死。
ANCHORS = dict(ANCHORS)
ANCHORS["U_TOUCH"] = (26.0, 31.0, 270)
# 背面翻转会交换竖放电阻两个焊盘的上下位置；反转 R_SIOC，令 +2V8
# 焊盘仍朝向 J_CAM pin 21，复用 C 已经 DRC 验证的细间距逃逸通道。
ANCHORS["R_SIOC"] = (8.0, 8.5, 270)


FRONT_ASSEMBLY = {
    "U1", "C_U1", "C_U1_BULK", "SW_RST", "SW_BOOT",
    "C_CAM_AVDD", "C_CAM_DVDD",
    *EDGE_CONNECTORS,
}

# placement_C 中所有装配件都出现在 NEAR / ANCHORS / DECOUPLING 之一；
# 集合差使新增摄像头阻容默认落到背面，同时保留两颗 U1 本地去耦在正面。
BACK_PARTS = (
    set(NEAR) | set(ANCHORS) | set(DECOUPLING) | set(DECOUPLING_ANCHORS)
) - FRONT_ASSEMBLY - {"H1", "H2"}

# C 的定点去耦坐标按正面焊盘方向计算；D 除两颗 J_CAM 就地电容外
# 全部翻面，必须让生成器按翻面后的真实引脚位置重新放置。
DECOUPLING_ANCHORS = {
    "C_CAM_AVDD": (11.75, 8.0, 270),
    "C_CAM_DVDD": (10.5, 8.0, 270),
}

# 背面上沿中右预留测试带；摄像头 LDO 在左上，不与测试点争位。
BACK_RESERVATIONS = [(20.0, 0.5, W - 0.5, 7.0)]
BACK_NEAR = {
    "TP_VUSB": (22.0, 3.0), "TP_VSYS": (27.5, 3.0), "TP_VBAT": (33.0, 3.0),
    "TP_3V3": (38.5, 3.0), "TP_GND": (44.0, 3.0), "TP_CC": (49.5, 3.0),
    "TP_EN": (55.0, 3.0), "TP_BOOT": (60.5, 3.0),
}

# D 翻面后按真实焊盘坐标选的平面逃逸点；每个点在写入前都经
# fanout.clear()/via_ok() 和最终 DRC 验证。J_CAM 仍在正面，故沿用 C 的 GND 逃逸点。
FANOUT_ANCHORS = {
    ("J_CAM", "23"): (7.25, 7.50),
    ("R_NTC", "1"): (48.52, 51.25),
    ("U_IMU", "10"): (31.9285, 38.8575),
}

# J_CAM 细间距焊盘的 +2V8 只能从相邻摄像头信号扇出之间穿出；
# D 的双面器件又占用了背面通道，因此收尾时用更细网格并限制在接口局部搜索。
ROUTING_GRID = dict(ROUTING_GRID)
ROUTING_GRID["+2V8"] = 0.05
ROUTING_MARGIN = dict(ROUTING_MARGIN)
ROUTING_MARGIN["+2V8"] = 5.0
