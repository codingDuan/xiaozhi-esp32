#pragma once

#include "esp_err.h"

#include <stddef.h>
#include <stdint.h>

struct FakeI2cBus;
struct FakeI2cDevice;

using i2c_master_bus_handle_t = FakeI2cBus*;
using i2c_master_dev_handle_t = FakeI2cDevice*;

enum {
    I2C_ADDR_BIT_LEN_7 = 0,
};

struct i2c_device_config_t {
    int dev_addr_length;
    uint16_t device_address;
    uint32_t scl_speed_hz;
};

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,
                                    const i2c_device_config_t* config,
                                    i2c_master_dev_handle_t* device);
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device);
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t device,
                              const uint8_t* data,
                              size_t data_size,
                              int timeout_ms);
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t device,
                                      const uint8_t* write_data,
                                      size_t write_size,
                                      uint8_t* read_data,
                                      size_t read_size,
                                      int timeout_ms);
