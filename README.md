# 微多普勒时频图数据增广项目

基于 Diffusers 的两阶段扩散模型，用于微多普勒时频图的数据增广。

## 🎯 项目概述

- **数据集**: 256×256 彩色微多普勒时频图像
- **用户数**: 31位用户的步态数据
- **目标**: 通过条件扩散生成指定用户的步态微多普勒时频图像
- **技术栈**: PyTorch + Diffusers + VAE + UNet

## 🏗️ 技术方案

### 第一阶段: VAE (变分自编码器)
- 将 256×256 图像编码到潜在空间 (32×32×4)
- 学习连续的视觉表示
- 压缩数据维度，提高训练效率
- 使用 AutoencoderKL (Stable Diffusion 同款)

### 第二阶段: 条件扩散
- 在潜在空间中进行扩散训练
- 以用户ID作为条件信息 (交叉注意力)
- 生成指定用户的微多普勒图像
- 使用 UNet2DConditionModel

## 🚀 快速开始

### Kaggle环境 (推荐)

如果您在Kaggle上运行，使用专用脚本：

```bash
# 一键训练 (适配您的数据集结构)
python train_kaggle.py --stage all

# 查看详细说明
cat KAGGLE_README.md
```

### 本地环境

#### 1. 环境设置
```bash
# 自动设置环境
python setup_environment.py

# 或手动安装
pip install -r requirements.txt
```

#### 2. 测试环境
```bash
# 运行完整测试
python test_pipeline.py

# 测试特定组件
python test_pipeline.py --test data
```

#### 3. 准备数据
支持两种数据结构：

**Kaggle格式** (您的数据集):
```
/kaggle/input/dataset/
├── ID_1/
├── ID_2/
└── ID_31/
```

**标准格式**:
```
data/
├── user_01/
├── user_02/
└── user_31/
```

#### 4. 训练模型

**Kaggle环境**:
```bash
# 使用优化的Kaggle配置
python train_kaggle.py --stage all
```

**本地环境**:
```bash
# 第一阶段: VAE训练
python training/train_vae.py --data_dir ./data --output_dir ./outputs/vae

# 第二阶段: 条件扩散训练
python training/train_diffusion.py \
    --data_dir ./data \
    --vae_path ./outputs/vae/final_model \
    --output_dir ./outputs/diffusion
```

#### 5. 生成图像
```bash
# 生成指定用户的图像
python inference/generate.py \
    --vae_path ./outputs/vae/final_model \
    --unet_path ./outputs/diffusion/final_model/unet \
    --condition_encoder_path ./outputs/diffusion/final_model/condition_encoder.pt \
    --num_users 31 \
    --user_ids 1 5 10 \
    --num_images_per_user 5
```

## 📁 项目结构

```
├── data/                   # 数据集目录
├── training/              # 训练脚本
│   ├── train_vae.py      # VAE训练
│   └── train_diffusion.py # 条件扩散训练
├── inference/             # 推理脚本
│   └── generate.py       # 条件生成
├── utils/                 # 工具函数
│   ├── data_loader.py    # 数据加载器
│   └── metrics.py        # 评估指标
├── outputs/               # 训练输出
├── TRAINING_GUIDE.md      # 详细训练指南
├── test_pipeline.py       # 测试脚本
└── setup_environment.py   # 环境设置
```

## 📋 环境要求

- **Python**: 3.8+
- **PyTorch**: 2.0+
- **GPU**: 8GB+ VRAM (推荐16GB)
- **CUDA**: 11.8+
- **依赖**: 见 requirements.txt

## 📊 性能基准

| 配置 | GPU内存 | 训练时间 | 批次大小 |
|------|---------|----------|----------|
| 最低 | 8GB | VAE: 3天, 扩散: 5天 | 4 |
| 推荐 | 16GB | VAE: 2天, 扩散: 3天 | 8 |
| 高端 | 24GB+ | VAE: 1天, 扩散: 2天 | 16+ |

## 🎯 预期结果

- **VAE重建PSNR**: > 25 dB
- **VAE重建SSIM**: > 0.8
- **FID分数**: < 50
- **条件控制**: 准确生成指定用户特征

## 📖 详细文档

- **[Kaggle专用指南](KAGGLE_README.md)** - 针对您的数据集的优化配置
- **[微多普勒数据增广说明](MICRO_DOPPLER_AUGMENTATION.md)** - 数据增广 vs 传统增强
- [完整训练指南](TRAINING_GUIDE.md) - 详细的训练步骤和参数调优
- [技术分析](technical_analysis.md) - 模型架构详细分析
- [VAE vs VQ-VAE对比](vae_vs_vqvae_analysis.md) - 技术选择分析

## 🔧 故障排除

常见问题及解决方案：

1. **CUDA内存不足**: 减小batch_size，使用混合精度训练
2. **VAE重建模糊**: 调整KL权重和感知损失权重
3. **扩散训练不收敛**: 降低学习率，增加训练步数
4. **生成质量差**: 增加推理步数，调整引导强度

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License
