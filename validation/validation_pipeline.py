#!/usr/bin/env python3
"""
现代化的条件扩散模型验证系统
参考成熟项目的设计模式，提供完整的验证流程
"""

import os
import sys
import argparse
import json
import torch
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# 添加项目根目录到Python路径
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from validation.user_classifier import UserValidationSystem

@dataclass
class ValidationConfig:
    """验证配置类 - 参考HuggingFace的配置模式"""
    # 基本配置
    target_user_id: int
    real_data_root: str
    output_dir: str = "./validation_results"
    
    # 分类器配置
    classifier_epochs: int = 30
    classifier_batch_size: int = 32
    classifier_lr: float = 5e-4
    max_samples_per_class: int = 1000
    confidence_threshold: float = 0.8
    
    # 生成配置
    num_images_to_generate: int = 16
    guidance_scale: float = 15.0
    num_inference_steps: int = 50
    
    # 模型路径
    vae_path: Optional[str] = None
    unet_path: Optional[str] = None
    condition_encoder_path: Optional[str] = None
    
    # 设备配置
    device: str = "auto"
    
    def __post_init__(self):
        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

class ConditionalDiffusionValidator:
    """现代化的条件扩散模型验证器 - 参考Diffusers的Pipeline设计"""
    
    def __init__(self, config: ValidationConfig):
        self.config = config
        self.validation_system = UserValidationSystem(device=config.device)
        self.output_path = Path(config.output_dir)
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        # 模型组件 (延迟加载)
        self.vae = None
        self.unet = None
        self.condition_encoder = None
        self.scheduler = None
        self.user_id_mapping = None
        
    def load_models(self) -> bool:
        """加载所有必要的模型组件"""
        if not all([self.config.vae_path, self.config.unet_path, self.config.condition_encoder_path]):
            print("❌ 缺少模型路径，无法加载模型")
            return False
            
        try:
            print("📂 加载模型组件...")
            
            # 加载VAE
            from diffusers import AutoencoderKL
            self.vae = AutoencoderKL.from_pretrained(self.config.vae_path)
            self.vae = self.vae.to(self.config.device)
            print("  ✅ VAE加载完成")
            
            # 加载UNet
            from diffusers import UNet2DConditionModel
            self.unet = UNet2DConditionModel.from_pretrained(self.config.unet_path)
            self.unet = self.unet.to(self.config.device)
            print("  ✅ UNet加载完成")
            
            # 获取用户ID映射
            self.user_id_mapping = self._get_user_id_mapping()
            num_users = len(self.user_id_mapping)
            print(f"  📊 用户映射: {self.user_id_mapping}")
            
            # 加载条件编码器
            from training.train_diffusion import UserConditionEncoder
            self.condition_encoder = UserConditionEncoder(
                num_users=num_users,
                embed_dim=self.unet.config.cross_attention_dim
            )
            
            condition_encoder_state = torch.load(self.config.condition_encoder_path, map_location='cpu')
            self.condition_encoder.load_state_dict(condition_encoder_state)
            self.condition_encoder = self.condition_encoder.to(self.config.device)
            print("  ✅ 条件编码器加载完成")
            
            # 创建调度器
            from diffusers import DDPMScheduler
            self.scheduler = DDPMScheduler(
                num_train_timesteps=1000,
                beta_start=0.00085,
                beta_end=0.012,
                beta_schedule="scaled_linear",
                clip_sample=False,
            )
            print("  ✅ 调度器创建完成")
            
            return True
            
        except Exception as e:
            print(f"❌ 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_user_id_mapping(self) -> Dict[int, int]:
        """获取用户ID映射 - 与训练时保持一致"""
        data_path = Path(self.config.real_data_root)
        all_users = []
        
        for user_dir in data_path.iterdir():
            if user_dir.is_dir() and user_dir.name.startswith('ID_'):
                try:
                    user_id = int(user_dir.name.split('_')[1])
                    all_users.append(user_id)
                except ValueError:
                    continue
        
        all_users = sorted(all_users)
        return {user_id: idx for idx, user_id in enumerate(all_users)}
    
    def train_classifier(self) -> bool:
        """训练用户分类器"""
        print(f"\n🤖 训练用户 {self.config.target_user_id} 的分类器")
        print(f"  参数: epochs={self.config.classifier_epochs}, batch_size={self.config.classifier_batch_size}")
        
        try:
            # 准备数据
            image_paths, labels = self._prepare_classifier_data()
            
            if len(image_paths) == 0:
                print(f"❌ 没有可用的训练数据")
                return False
            
            # 训练分类器
            history = self.validation_system.train_user_classifier(
                user_id=self.config.target_user_id,
                image_paths=image_paths,
                labels=labels,
                epochs=self.config.classifier_epochs,
                batch_size=self.config.classifier_batch_size,
                learning_rate=self.config.classifier_lr
            )
            
            # 保存训练曲线
            plot_path = self.output_path / f"user_{self.config.target_user_id:02d}_training.png"
            self.validation_system.plot_training_history(history, str(plot_path))
            
            # 检查训练效果
            best_val_acc = max(history['val_acc'])
            print(f"  📊 最佳验证准确率: {best_val_acc:.3f}")
            
            return best_val_acc > 0.7  # 设定最低准确率要求
            
        except Exception as e:
            print(f"❌ 分类器训练失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _prepare_classifier_data(self) -> Tuple[List[str], List[int]]:
        """准备分类器训练数据"""
        data_path = Path(self.config.real_data_root)
        target_user_dir = None
        other_user_dirs = []
        
        # 查找目标用户和其他用户目录
        for item in data_path.iterdir():
            if item.is_dir():
                if item.name == f"ID_{self.config.target_user_id}":
                    target_user_dir = item
                elif item.name.startswith("ID_"):
                    try:
                        other_user_id = int(item.name.split("_")[1])
                        if other_user_id != self.config.target_user_id:
                            other_user_dirs.append(item)
                    except ValueError:
                        continue
        
        if target_user_dir is None:
            print(f"❌ 未找到用户 {self.config.target_user_id} 的数据目录")
            return [], []
        
        image_paths = []
        labels = []
        
        # 正样本 (目标用户)
        target_images = list(target_user_dir.glob("*.png")) + list(target_user_dir.glob("*.jpg"))
        target_images = target_images[:self.config.max_samples_per_class]
        
        for img_path in target_images:
            image_paths.append(str(img_path))
            labels.append(1)  # 正类
        
        # 负样本 (其他用户)
        negative_count = 0
        for other_dir in other_user_dirs:
            if negative_count >= self.config.max_samples_per_class:
                break
            
            other_images = list(other_dir.glob("*.png")) + list(other_dir.glob("*.jpg"))
            for img_path in other_images:
                if negative_count >= self.config.max_samples_per_class:
                    break
                image_paths.append(str(img_path))
                labels.append(0)  # 负类
                negative_count += 1
        
        print(f"  📊 数据统计: 正样本 {sum(labels)}, 负样本 {len(labels) - sum(labels)}")
        return image_paths, labels

    def generate_images(self) -> Optional[str]:
        """生成指定用户的图像"""
        if not all([self.vae, self.unet, self.condition_encoder, self.scheduler]):
            print("❌ 模型未加载，无法生成图像")
            return None

        if self.config.target_user_id not in self.user_id_mapping:
            print(f"❌ 用户 {self.config.target_user_id} 不在映射中")
            return None

        print(f"\n🎨 生成用户 {self.config.target_user_id} 的图像")
        print(f"  参数: guidance_scale={self.config.guidance_scale}, steps={self.config.num_inference_steps}")

        try:
            # 创建输出目录
            gen_output_dir = self.output_path / "generated_images" / f"user_{self.config.target_user_id:02d}"
            gen_output_dir.mkdir(parents=True, exist_ok=True)

            # 获取用户索引
            user_idx = self.user_id_mapping[self.config.target_user_id]

            # 设置调度器
            self.scheduler.set_timesteps(self.config.num_inference_steps)

            # 生成图像
            self.vae.eval()
            self.unet.eval()
            self.condition_encoder.eval()

            with torch.no_grad():
                for i in range(self.config.num_images_to_generate):
                    print(f"  生成第 {i+1}/{self.config.num_images_to_generate} 张...")

                    # 随机噪声
                    latents = torch.randn(1, 4, 32, 32, device=self.config.device)

                    # 用户条件
                    user_tensor = torch.tensor([user_idx], device=self.config.device)
                    user_embedding = self.condition_encoder(user_tensor)

                    # 确保3D张量格式
                    if user_embedding.dim() == 2:
                        user_embedding = user_embedding.unsqueeze(1)

                    # 扩散过程
                    latents = latents * self.scheduler.init_noise_sigma

                    for t in self.scheduler.timesteps:
                        # 有条件预测
                        noise_pred_cond = self.unet(
                            latents,
                            t,
                            encoder_hidden_states=user_embedding
                        ).sample

                        # 无条件预测
                        zero_embedding = torch.zeros_like(user_embedding)
                        noise_pred_uncond = self.unet(
                            latents,
                            t,
                            encoder_hidden_states=zero_embedding
                        ).sample

                        # 分类器自由指导
                        noise_pred = noise_pred_uncond + self.config.guidance_scale * (noise_pred_cond - noise_pred_uncond)

                        # 调度器步骤
                        latents = self.scheduler.step(noise_pred, t, latents).prev_sample

                    # 解码为图像
                    vae_model = self.vae.module if hasattr(self.vae, 'module') else self.vae
                    latents = latents / vae_model.config.scaling_factor
                    images = vae_model.decode(latents).sample
                    images = images.clamp(0, 1)

                    # 保存图像
                    from PIL import Image
                    image = images.cpu().permute(0, 2, 3, 1).numpy()[0]
                    image = (image * 255).astype(np.uint8)
                    pil_image = Image.fromarray(image)

                    save_path = gen_output_dir / f"user_{self.config.target_user_id}_generated_{i+1:02d}.png"
                    pil_image.save(save_path)

            print(f"  ✅ 生成完成，保存在: {gen_output_dir}")
            return str(gen_output_dir)

        except Exception as e:
            print(f"❌ 图像生成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def validate_generated_images(self, generated_images_dir: str) -> Dict:
        """验证生成图像"""
        print(f"\n🔍 验证生成图像")

        try:
            result = self.validation_system.validate_generated_images(
                user_id=self.config.target_user_id,
                generated_images_dir=generated_images_dir,
                confidence_threshold=self.config.confidence_threshold
            )

            # 保存验证结果
            result_path = self.output_path / f"user_{self.config.target_user_id:02d}_validation.json"
            with open(result_path, 'w') as f:
                json.dump(result, f, indent=2)

            return result

        except Exception as e:
            print(f"❌ 验证失败: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def run_full_pipeline(self, generate_images: bool = True) -> Dict:
        """运行完整的验证流程"""
        print(f"🚀 开始完整验证流程")
        print(f"目标用户: {self.config.target_user_id}")
        print(f"输出目录: {self.config.output_dir}")
        print("=" * 60)

        results = {
            "target_user_id": self.config.target_user_id,
            "config": self.config.__dict__,
            "classifier_trained": False,
            "images_generated": False,
            "validation_completed": False,
            "success": False
        }

        # 步骤1: 训练分类器
        if not self.train_classifier():
            print("❌ 分类器训练失败，终止流程")
            return results

        results["classifier_trained"] = True

        # 步骤2: 生成图像 (可选)
        generated_dir = None
        if generate_images:
            if not self.load_models():
                print("❌ 模型加载失败，跳过图像生成")
            else:
                generated_dir = self.generate_images()
                if generated_dir:
                    results["images_generated"] = True
                    results["generated_images_dir"] = generated_dir

        # 步骤3: 验证图像
        if generated_dir:
            validation_result = self.validate_generated_images(generated_dir)
            if validation_result:
                results["validation_completed"] = True
                results["validation_result"] = validation_result

                # 判断整体成功
                success_rate = validation_result.get('success_rate', 0)
                avg_confidence = validation_result.get('avg_confidence', 0)

                if success_rate >= 0.6 and avg_confidence >= 0.8:
                    results["success"] = True
                    print(f"🎉 验证成功! 成功率: {success_rate:.2f}, 平均置信度: {avg_confidence:.3f}")
                else:
                    print(f"⚠️  验证结果不理想. 成功率: {success_rate:.2f}, 平均置信度: {avg_confidence:.3f}")
                    print(f"💡 建议: 尝试更高的指导强度 (guidance_scale > {self.config.guidance_scale})")

        return results

def main():
    """主函数 - 现代化的命令行接口"""
    parser = argparse.ArgumentParser(
        description="现代化的条件扩散模型验证系统",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # 必需参数
    parser.add_argument("--target_user_id", type=int, required=True,
                       help="目标用户ID")
    parser.add_argument("--real_data_root", type=str, required=True,
                       help="真实数据根目录")

    # 基本配置
    parser.add_argument("--output_dir", type=str, default="./validation_results",
                       help="输出目录")
    parser.add_argument("--device", type=str, default="auto",
                       help="计算设备 (auto/cuda/cpu)")

    # 分类器配置
    parser.add_argument("--classifier_epochs", type=int, default=30,
                       help="分类器训练轮数")
    parser.add_argument("--classifier_batch_size", type=int, default=32,
                       help="分类器批次大小")
    parser.add_argument("--classifier_lr", type=float, default=5e-4,
                       help="分类器学习率")
    parser.add_argument("--max_samples_per_class", type=int, default=1000,
                       help="每类最大样本数")
    parser.add_argument("--confidence_threshold", type=float, default=0.8,
                       help="置信度阈值")

    # 生成配置
    parser.add_argument("--generate_images", action="store_true",
                       help="是否生成图像")
    parser.add_argument("--num_images_to_generate", type=int, default=16,
                       help="生成图像数量")
    parser.add_argument("--guidance_scale", type=float, default=15.0,
                       help="指导强度 (微多普勒建议15-50)")
    parser.add_argument("--num_inference_steps", type=int, default=50,
                       help="推理步数")

    # 模型路径
    parser.add_argument("--vae_path", type=str,
                       help="VAE模型路径")
    parser.add_argument("--unet_path", type=str,
                       help="UNet模型路径")
    parser.add_argument("--condition_encoder_path", type=str,
                       help="条件编码器路径")

    args = parser.parse_args()

    # 创建配置
    config = ValidationConfig(
        target_user_id=args.target_user_id,
        real_data_root=args.real_data_root,
        output_dir=args.output_dir,
        classifier_epochs=args.classifier_epochs,
        classifier_batch_size=args.classifier_batch_size,
        classifier_lr=args.classifier_lr,
        max_samples_per_class=args.max_samples_per_class,
        confidence_threshold=args.confidence_threshold,
        num_images_to_generate=args.num_images_to_generate,
        guidance_scale=args.guidance_scale,
        num_inference_steps=args.num_inference_steps,
        vae_path=args.vae_path,
        unet_path=args.unet_path,
        condition_encoder_path=args.condition_encoder_path,
        device=args.device
    )

    # 打印配置
    print("🔧 验证配置:")
    print(f"  目标用户: {config.target_user_id}")
    print(f"  数据目录: {config.real_data_root}")
    print(f"  输出目录: {config.output_dir}")
    print(f"  分类器: epochs={config.classifier_epochs}, batch_size={config.classifier_batch_size}")
    if args.generate_images:
        print(f"  生成: guidance_scale={config.guidance_scale}, steps={config.num_inference_steps}")
        print(f"  模型: VAE={config.vae_path is not None}, UNet={config.unet_path is not None}")
    print("=" * 60)

    # 创建验证器并运行
    validator = ConditionalDiffusionValidator(config)
    results = validator.run_full_pipeline(generate_images=args.generate_images)

    # 输出结果
    print(f"\n📋 验证结果总结:")
    print(f"  分类器训练: {'✅' if results['classifier_trained'] else '❌'}")
    if args.generate_images:
        print(f"  图像生成: {'✅' if results['images_generated'] else '❌'}")
        print(f"  验证完成: {'✅' if results['validation_completed'] else '❌'}")
        print(f"  整体成功: {'🎉' if results['success'] else '⚠️'}")

    # 保存完整结果
    result_file = Path(config.output_dir) / f"user_{config.target_user_id:02d}_complete_results.json"
    with open(result_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n📄 完整结果保存在: {result_file}")

    if results.get('success'):
        print("🎉 验证成功完成!")
        return 0
    else:
        print("⚠️  验证未完全成功，请检查结果并调整参数")
        return 1

if __name__ == "__main__":
    exit(main())
