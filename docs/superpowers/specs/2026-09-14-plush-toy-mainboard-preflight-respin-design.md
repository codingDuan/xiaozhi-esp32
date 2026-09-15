# 毛绒玩具主板打样前改版设计

**日期**：2026-09-14

**状态**：已获委托方方案确认，待实施计划

**基线**：`3271c54 feat(pcb): complete plush toy mainboard routing`

## 1. 目标与范围

在不改变 `main/boards/plush-toy/config.h` GPIO 分配的前提下，对首版 PCB 做一次完整 respin，消除已经量化确认的电源保护、降压热环路、ESP32 供电/复位、摄像头时钟、外接触摸线和制造输出风险。改版必须由现有代码生成原理图与 PCB，并重新完成布线、DRC、制造资料导出和双面渲染。

本次不改变板框 90×60mm、四层板、全部器件正面贴装、VBUS/VMOT 双电源域隔离和 PGND/GND 单点汇合架构。固件功能和 GPIO 映射不在范围内。

## 2. 已确认的基线问题

基线板的只读测量结果如下：

- J_VMOT 和 J_SERVO_L/R 只有位号，没有电压、用途、极性或通道丝印。
- SY8089 输入工作范围上限为 5.5V，MAX98357A VDD 绝对最大值为 6V；USB 热插拔后没有能限制 VBUS 过冲的器件。
- BUCK_SW 铜长 7.25mm，含 2 个换层过孔和约 3.8mm B.Cu 走线；U_BUCK.2 与 C_BUCK_IN.2 分处芯片两侧。
- C_U1、C_U1_BULK 到 U1.2 的中心距离分别为 24.47mm、26.27mm；R_EN、C_EN 到 U1.3 分别为 30.59mm、36.96mm；EN 铜长 52.84mm。
- CAM_XCLK 铜长 47.07mm，横跨 F.Cu/B.Cu，含 4 个过孔，没有专用地护线。
- R_SIOC、R_SIOD 当前为 DNP；TP_E0 是板内 1mm SMD 测试点。
- positions.csv 是 KiCad 原生列名，不是 JLCPCB 直接上传格式。
- U1 天线实体从左边伸出约 6.75mm；Gerber job 使用三段 0.48mm 默认介质厚度。
- D_LED 使用的 C965555 是额定 5V 的旧版 WS2812B-2020。
- C_NTC 实际为 100nF X7R，而旧设计文字写 C0G。
- TOUCH_E0 板上连接线下方为完整 L2 GND。由于真正的电极在板外，NXP 的建议是连接线参考完整地平面；这里不是缺陷，不应切割 L2。

## 3. 电路改动

### 3.1 USB VBUS 保护

不得使用 SMBJ5.0A 作为下游 6V 器件的唯一保护：该器件最低击穿电压 6.4V、最大钳位电压 9.2V，保护阈值过高。

逻辑电源入口改成：

```text
J_USB VBUS ─ VBUS_IN ─ F_USB ─ VBUS_FUSED ─ U_EFUSE ─ VBUS
                                            │
                                            ├─ C_EFUSE_IN 100nF → GND
                                            ├─ C_EFUSE_DVDT 3.3nF → GND
                                            └─ R_EFUSE_ILM 1.02k → GND
```

U_EFUSE 使用 TI TPS259531DSGR，LCSC C2155674，封装使用 KiCad 官方 `Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias`。项目库新增按 TI 数据手册绘制的符号，禁止借用引脚不一致的近似型号。

引脚连接固定为：1 dVdt 接 C_EFUSE_DVDT；2 EN/UVLO 接 VBUS_FUSED；3/4 IN 接 VBUS_FUSED；5 OUT 接 VBUS；6 FLT 明确 NC；7 ILM 经 1.02k 接 GND；8 和 exposed pad 接 GND。TPS259531 的输出钳位范围为 5.2–5.7V（典型值 5.45V），并支持自动重试；1.02k 将限流点设在约 1.9A，覆盖本板约 1.5A 逻辑域峰值；3.3nF 是数据手册允许的最小 dVdt 电容并限制上电斜率。

F_USB 保留，继续承担可恢复保险丝功能。SY8089、MAX98357A 和所有其他逻辑 5V 负载只允许连接 U_EFUSE 后的 `VBUS`，不得连接 `VBUS_IN` 或 `VBUS_FUSED`。

### 3.2 摄像头 SCCB

R_SIOC、R_SIOD 保持 4.7k、上拉到 +2V8，但改为必贴。两颗电阻使用现有 C25900 物料，不改变 GPIO4/GPIO5 或摄像头 FPC 定义。

### 3.3 头部触摸连接

删除 TP_E0，新增手焊连接器 J_TOUCH：

- 符号 `Connector_Generic:Conn_01x02`；
- 封装 `Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical`；
- 1 脚 TOUCH_E0，2 脚 GND；
- 放在靠近 U_TOUCH 的板边，插拔方向不得被相邻器件或线缆遮挡；
- 不进入自动贴装 BOM/CPL，进入手焊连接器清单。

板上 TOUCH_E0 连接线继续参考完整 L2 GND，不在 L2 挖空。使用时建议 E0/GND 成对走线并在线缆出口做结构应力释放。

### 3.4 状态灯

D_LED 的物料改为明确支持 3.3–5.5V 的 Worldsemi WS2812B-2020-V6，LCSC C52917434。继续使用 +3V3 供电和现有 GPIO48。实现时必须用官方 V6 数据手册核对 1=DO、2=GND、3=DI、4=VDD 以及推荐焊盘尺寸；引脚或焊盘不一致时新增项目封装，不能只换 BOM 料号。

### 3.5 测温电容

C_NTC 保持现有 100nF 0402 X7R C1525。旧设计文档中“C0G”改为“X7R”；该电容只作低通滤波，不改变电路或布局。

## 4. 布局与关键布线约束

### 4.1 降压热环路

U_BUCK、L_BUCK、C_BUCK_IN、C_BUCK_OUT1/2 和反馈网络作为一个不可拆分的布局单元重新放置。必须满足：

- U_BUCK.3 到 L_BUCK.1 的 BUCK_SW 全程 F.Cu、无过孔、总铜长不超过 3.0mm；
- U_BUCK.4 到 C_BUCK_IN.1 的焊盘中心距离不超过 2.5mm；
- U_BUCK.2 到 C_BUCK_IN.2 的焊盘中心距离不超过 2.5mm；
- C_BUCK_IN.2 和 U_BUCK.2 各自 1.0mm 内有 GND 过孔接 L2；
- 反馈分压靠近 U_BUCK.5，BUCK_FB 不与 BUCK_SW 平行；
- BUCK_SW 只位于顶层，并由完整 L2 GND 与 In2 的 +3V3 平面隔开；不得为了开关节点切割 L2。

这些关键铜在 Freerouting 之前由确定性脚本生成并锁定；自动布线不得重写。

### 4.2 ESP32 去耦与复位

- C_U1 100nF 和 C_U1_BULK 10uF 移到 U1.2 旁；各自 +3V3 焊盘到 U1.2 的中心距离不超过 4.0mm。
- 两颗电容的 GND 焊盘各自 1.0mm 内必须有 GND 过孔。
- R_EN 与 C_EN 移到 U1.3 旁；其 EN 焊盘到 U1.3 的中心距离均不超过 5.0mm。
- U1.3、R_EN、C_EN 组成的本地 EN 主干不超过 10mm且不换层。SW_RST 留在原位置，作为本地主干引出的长支路；按键支路不得穿过 BUCK_SW 区域。

### 4.3 摄像头 XCLK

CAM_XCLK 在 Freerouting 前确定性布线，满足：

- 从 U1.8 到 J_CAM.13 全程 F.Cu，换层过孔数为 0；
- 不与 CAM_Y8、CAM_Y9、CAM_HREF 或其他信号在 0.7mm 内平行超过 3mm；
- 两侧布置 GND 护线，护线到 XCLK 边缘的间距为 0.5–0.8mm；
- 护线每隔不超过 3mm 通过 GND 过孔连接 L2，路径端点也必须有地过孔；
- L2 在 XCLK 下方保持连续，不允许任何槽或局部挖空。

摄像头 D0–D7 与 PCLK 延续原设计的同层优先和长度差不超过 5mm要求；完整重布后重新测量。

### 4.4 丝印

新增的独立丝印文本必须使用不小于 1.0mm 字高和 0.15mm 线宽，并通过焊盘/文字重叠测试。最少包含：

- J_VMOT 旁：`电机/加热专用 5V`、`+` 对准 1 脚、`-` 对准 2 脚；
- J_SERVO_L 旁：`CH0 左`；
- J_SERVO_R 旁：`CH1 右`；
- J_HEAT 旁保留：`必须串 KSD9700 65度 常闭`；
- VMOT 功率区可见位置：`VMOT 仅限 5V`；
- J_TOUCH 旁：`头部触摸 E0 / GND`。

若空间不足，优先移动位号或器件，不能缩小安全丝印，也不能隐藏这些文本。

## 5. 叠层、天线和制造资料

### 5.1 叠层

KiCad 工程叠层改为 JLC04161H-7628、1.6mm、外层 1oz、内层 0.5oz：

```text
F.Cu       0.0350mm
7628 PP    0.2104mm
In1.Cu     0.0152mm
Core       1.0650mm
In2.Cu     0.0152mm
7628 PP    0.2104mm
B.Cu       0.0350mm
```

Gerber job 的 MaterialStackup 必须与上述数值一致。L2 仍为完整 GND，L3 仍为逻辑电源平面。README 和下单清单必须写明选择 JLC04161H-7628；如果下单选择阻抗控制，USB D+/D- 使用 JLCPCB 计算器针对该叠层给出的 90Ω 差分参数，不能沿用 KiCad 默认叠层推算值。

### 5.2 天线与工艺边

保持 U1 位置和天线伸出左板边的方式。README/TESTING 明确要求：

- 拼板或增加工艺边时只允许上下两侧，左侧不得加板材、铜或工艺边；
- 外壳在天线方向尽量保留 15mm 空间，不放电池、线束、金属件或高介电材料；
- 首板必须测试 Wi-Fi 吞吐、连接稳定性和实际使用姿态下的通信距离。

### 5.3 BOM/CPL

positions.csv 直接输出 JLCPCB 列名和顺序：

```text
Designator,Mid X,Mid Y,Layer,Rotation
```

坐标单位固定为 mm，Layer 只能是 `Top` 或 `Bottom`，Rotation 归一化到 `[0, 360)`。BOM 与 CPL 位号集合必须完全相等，不再把自动贴装总数硬编码为 74；期望集合从 `board_spec.PARTS` 的 fitted、自动贴装属性和手焊清单动态推导。

J_TOUCH 与既有八个板外接线座列入手焊清单。导出脚本继续先在临时目录生成并验证，再原子替换 `fab/`。JLCPCB 上传后的贴片预览仍必须逐颗核对所有 IC、二极管、LED、电解电容和连接器的 1 脚/极性；自动生成文件不能替代该人工门禁。

## 6. 生成与验证策略

所有源事实继续由代码拥有：

- `board_spec.py`：新增 eFuse 网络与器件、SCCB 必贴、J_TOUCH、V6 LED；
- `gen_schematic.py`：生成对应原理图和明确 NC；
- `placement.py`：新布局坐标及安全丝印；
- `gen_pcb.py`：真实叠层、丝印、平面和工程元数据；
- `fanout.py`：降压热环路、U1 去耦/EN 与 XCLK 的确定性关键铜；
- `post_route.py`：只补剩余连接并执行完整工程 DRC，不得删除关键锁定铜；
- `fab_tools.py` / `export_fab.sh`：JLCPCB CPL、动态 BOM/CPL 集合验证、Gerber stackup 验证。

每项生产改动先增加能在旧板上稳定失败的测试，再修改生成器。最终验收至少包括：

1. board_spec 引脚、物料、双电源域隔离和 SCCB 上拉测试；
2. eFuse 保护路径中所有 VBUS 负载只能位于 OUT 后测试；
3. 降压器件距离、BUCK_SW 层/长度/过孔和本地地过孔测试；
4. U1 去耦与 EN RC 距离、主干长度测试；
5. XCLK 层、过孔、邻近平行线、护线与地过孔间距测试；
6. J_TOUCH PTH/网络/手焊属性测试；
7. 丝印内容、尺寸、焊盘和文字净距测试；
8. 真实叠层字段和 Gerber job 一致性测试；
9. JLCPCB CPL 表头、单位、层名、角度范围以及 BOM/CPL 全集合一致性测试；
10. 完整 ERC、DRC、未连接、原理图一致性和双面渲染人工检查。

改版完成的静态终态为：ERC 0 error；DRC 0 error；未连接 0；原理图一致性 0；除精确审阅的 U1 标准封装丝印板边告警外不得有其他 warning。成功构建和静态检查不等于硬件验证，USB 热插拔波形、3V3 纹波、XCLK 信号完整性、摄像头图像、触摸基线、LED 颜色和天线性能仍需首板实测。

## 7. 文档修订

实施时同步修订原 4 层设计方案：加入 eFuse 电源框图；把 SCCB 改为必贴；把 C_NTC 介质改为 X7R；记录 V6 LED；加入 J_TOUCH；补充真实叠层和工艺边约束。README 状态必须在重布线期间回退为“改版中”，只有新 Gerber/BOM/CPL 重新验证后才能恢复“静态检查完成”。
