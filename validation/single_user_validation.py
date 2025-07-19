#!/usr/bin/env python3
"""
单用户验证脚本
只训练一个用户的分类器，验证该用户的生成图像
适合显存有限的环境
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import List

# 添加项目根目录到Python路径
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from validation.user_classifier import UserValidationSystem

def single_user_workflow(
    target_user_id: int,
    real_data_root: str,
    generated_images_dir: str = None,
    output_dir: str = "./single_user_validation",
    epochs: int = 15,
    batch_size: int = 16,  # 减少batch_size节省显存
    learning_rate: float = 1e-3,
    max_samples_per_class: int = 300,  # 减少样本数量
    confidence_threshold: float = 0.8,
    generate_images: bool = False,
    vae_path: str = None,
    unet_path: str = None,
    condition_encoder_path: str = None,
    num_images_to_generate: int = 8  # 减少生成数量
):
    """
    单用户完整验证工作流程
    
    Args:
        target_user_id: 目标用户ID
        real_data_root: 真实数据根目录
        generated_images_dir: 生成图像目录 (如果已有)
        output_dir: 输出目录
        epochs: 训练轮数
        batch_size: 批次大小 (减少以节省显存)
        learning_rate: 学习率
        max_samples_per_class: 每类最大样本数
        confidence_threshold: 置信度阈值
        generate_images: 是否生成图像
        vae_path: VAE路径 (生成图像时需要)
        unet_path: UNet路径 (生成图像时需要)
        condition_encoder_path: 条件编码器路径 (生成图像时需要)
        num_images_to_generate: 生成图像数量
    """
    
    print(f"🎯 单用户验证工作流程")
    print(f"目标用户: {target_user_id}")
    print(f"输出目录: {output_dir}")
    print("=" * 50)
    
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 初始化验证系统
    validation_system = UserValidationSystem()
    
    # 步骤1: 准备训练数据
    print(f"\n📁 步骤1: 准备用户 {target_user_id} 的训练数据")
    
    # 查找用户数据目录
    data_root = Path(real_data_root)
    target_user_dir = None
    other_user_dirs = []
    
    for user_dir in data_root.iterdir():
        if user_dir.is_dir() and user_dir.name.startswith('user_'):
            try:
                user_id = int(user_dir.name.split('_')[1])
                if user_id == target_user_id:
                    target_user_dir = str(user_dir)
                    print(f"  ✅ 找到目标用户目录: {user_dir}")
                else:
                    other_user_dirs.append(str(user_dir))
            except (IndexError, ValueError):
                continue
    
    if target_user_dir is None:
        print(f"❌ 未找到用户 {target_user_id} 的数据目录")
        return False
    
    print(f"  📊 找到 {len(other_user_dirs)} 个其他用户目录作为负样本")
    
    # 准备训练数据
    image_paths, labels = validation_system.prepare_user_data(
        user_id=target_user_id,
        real_images_dir=target_user_dir,
        other_users_dirs=other_user_dirs,
        max_samples_per_class=max_samples_per_class
    )
    
    if len(image_paths) == 0:
        print(f"❌ 用户 {target_user_id} 没有可用的训练数据")
        return False
    
    # 检查数据平衡性
    positive_count = sum(labels)
    negative_count = len(labels) - positive_count
    print(f"  📊 数据分布: 正样本 {positive_count}, 负样本 {negative_count}")
    
    # 步骤2: 训练分类器
    print(f"\n🎯 步骤2: 训练用户 {target_user_id} 的分类器")
    
    try:
        history = validation_system.train_user_classifier(
            user_id=target_user_id,
            image_paths=image_paths,
            labels=labels,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate
        )
        
        # 保存分类器和训练历史
        classifier_path = output_path / f"user_{target_user_id:02d}_classifier.pth"
        validation_system.save_classifier(target_user_id, str(classifier_path))
        
        history_path = output_path / f"user_{target_user_id:02d}_history.json"
        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)
        
        # 绘制训练曲线
        plot_path = output_path / f"user_{target_user_id:02d}_training.png"
        validation_system.plot_training_history(history, str(plot_path))
        
        print(f"✅ 分类器训练完成")
        
    except Exception as e:
        print(f"❌ 分类器训练失败: {e}")
        return False
    
    # 步骤3: 生成图像 (可选)
    if generate_images:
        print(f"\n🎨 步骤3: 生成用户 {target_user_id} 的图像")
        
        if not all([vae_path, unet_path, condition_encoder_path]):
            print("❌ 生成图像需要提供VAE、UNet和条件编码器路径")
            return False
        
        # 生成图像目录
        gen_output_dir = output_path / "generated_images" / f"user_{target_user_id:02d}"
        gen_output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 调用生成脚本
            import subprocess
            
            cmd = [
                "python", str(project_root / "inference" / "generate_training_style.py"),
                "--vae_path", vae_path,
                "--unet_path", unet_path,
                "--condition_encoder_path", condition_encoder_path,
                "--num_users", "31",
                "--user_ids", str(target_user_id),
                "--num_images_per_user", str(num_images_to_generate),
                "--num_inference_steps", "20",  # 减少步数节省时间
                "--output_dir", str(output_path / "generated_images"),
                "--device", "auto"
            ]
            
            print(f"  🚀 执行生成命令...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"  ✅ 图像生成完成")
                generated_images_dir = str(gen_output_dir)
            else:
                print(f"  ❌ 图像生成失败: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ 图像生成异常: {e}")
            return False
    
    # 步骤4: 验证生成图像
    if generated_images_dir:
        print(f"\n🔍 步骤4: 验证生成图像")
        
        gen_dir = Path(generated_images_dir)
        if not gen_dir.exists():
            print(f"❌ 生成图像目录不存在: {gen_dir}")
            return False
        
        try:
            # 验证生成图像
            result = validation_system.validate_generated_images(
                user_id=target_user_id,
                generated_images_dir=str(gen_dir),
                confidence_threshold=confidence_threshold
            )
            
            # 保存验证结果
            result_path = output_path / f"user_{target_user_id:02d}_validation.json"
            with open(result_path, 'w') as f:
                json.dump(result, f, indent=2)
            
            # 生成简单报告
            report_path = output_path / "validation_report.md"
            report_text = validation_system.generate_validation_report([result], str(report_path))
            
            # 打印结果
            print(f"\n📊 验证结果:")
            print(f"  图像数量: {result['total_images']}")
            print(f"  成功数量: {result['success_count']}")
            print(f"  成功率: {result['success_rate']:.1%}")
            print(f"  平均置信度: {result['avg_confidence']:.3f}")
            print(f"  置信度范围: [{result['min_confidence']:.3f}, {result['max_confidence']:.3f}]")
            
            # 效果评估
            success_rate = result['success_rate']
            if success_rate >= 0.8:
                print(f"🎉 优秀！生成图像很好地保持了用户 {target_user_id} 的特征")
            elif success_rate >= 0.6:
                print(f"✅ 良好！生成图像较好地保持了用户 {target_user_id} 的特征")
            elif success_rate >= 0.4:
                print(f"⚠️  一般！生成图像部分保持了用户 {target_user_id} 的特征")
            else:
                print(f"❌ 较差！生成图像未能很好保持用户 {target_user_id} 的特征")
            
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            return False
    
    print(f"\n🎉 单用户验证工作流程完成！")
    print(f"📁 所有结果保存在: {output_dir}")
    
    return True

def main():
    parser = argparse.ArgumentParser(description="单用户验证工作流程")
    
    # 必需参数
    parser.add_argument("--target_user_id", type=int, required=True,
                       help="目标用户ID")
    parser.add_argument("--real_data_root", type=str, required=True,
                       help="真实数据根目录")
    
    # 可选参数
    parser.add_argument("--generated_images_dir", type=str,
                       help="已有的生成图像目录 (如果不提供且不生成，则跳过验证)")
    parser.add_argument("--output_dir", type=str, default="./single_user_validation",
                       help="输出目录")
    
    # 训练参数 (针对显存优化)
    parser.add_argument("--epochs", type=int, default=15, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=16, help="批次大小 (减少以节省显存)")
    parser.add_argument("--learning_rate", type=float, default=1e-3, help="学习率")
    parser.add_argument("--max_samples_per_class", type=int, default=300, help="每类最大样本数")
    
    # 验证参数
    parser.add_argument("--confidence_threshold", type=float, default=0.8,
                       help="置信度阈值")
    
    # 生成参数 (可选)
    parser.add_argument("--generate_images", action="store_true",
                       help="是否生成图像")
    parser.add_argument("--vae_path", type=str, help="VAE路径")
    parser.add_argument("--unet_path", type=str, help="UNet路径")
    parser.add_argument("--condition_encoder_path", type=str, help="条件编码器路径")
    parser.add_argument("--num_images_to_generate", type=int, default=8,
                       help="生成图像数量")
    
    args = parser.parse_args()
    
    print("🎯 单用户验证工作流程")
    print("=" * 50)
    print(f"目标用户ID: {args.target_user_id}")
    print(f"真实数据根目录: {args.real_data_root}")
    print(f"输出目录: {args.output_dir}")
    print(f"训练参数: epochs={args.epochs}, batch_size={args.batch_size}")
    if args.generate_images:
        print(f"将生成 {args.num_images_to_generate} 张图像")
    print("=" * 50)
    
    success = single_user_workflow(
        target_user_id=args.target_user_id,
        real_data_root=args.real_data_root,
        generated_images_dir=args.generated_images_dir,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        max_samples_per_class=args.max_samples_per_class,
        confidence_threshold=args.confidence_threshold,
        generate_images=args.generate_images,
        vae_path=args.vae_path,
        unet_path=args.unet_path,
        condition_encoder_path=args.condition_encoder_path,
        num_images_to_generate=args.num_images_to_generate
    )
    
    if success:
        print("\n✅ 工作流程成功完成！")
    else:
        print("\n❌ 工作流程失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
