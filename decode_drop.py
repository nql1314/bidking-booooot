import base64
import os

# Drop.txt 文件路径
drop_file = 'F:/SteamLibrary/steamapps/common/BidKing/BidKing_Data/StreamingAssets/Tables/Drop.txt'
output_file = 'F:/SteamLibrary/steamapps/common/BidKing/BidKing_Data/StreamingAssets/Tables/Drop_decoded.txt'

def decode_drop_table():
    """解码 Drop.txt 文件"""
    
    # 检查文件是否存在
    if not os.path.exists(drop_file):
        print(f"错误: 文件不存在 - {drop_file}")
        return
    
    # 读取 Base64 编码内容
    with open(drop_file, 'r', encoding='utf-8') as f:
        encoded_content = f.read().strip()
    
    print(f"成功读取文件，内容长度: {len(encoded_content)} 字符")
    
    # Base64 解码
    try:
        decoded_bytes = base64.b64decode(encoded_content)
        decoded_text = decoded_bytes.decode('utf-8')
        
        print(f"解码成功，解码后长度: {len(decoded_text)} 字符")
        
        # 按行分割
        lines = decoded_text.strip().split('\r\n')
        print(f"总行数: {len(lines)}")
        
        # 显示前几行的结构
        print("\n前 3 行数据结构:")
        for i, line in enumerate(lines[:3]):
            cols = line.split('\t')
            print(f"  行 {i}: {len(cols)} 列")
            for j, col in enumerate(cols[:10]):  # 只显示前10列
                print(f"    列 {j}: {col}")
            print()
        
        # 保存解码后的内容
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(decoded_text)
        
        print(f"解码后的文件已保存到: {output_file}")
        
        return lines
        
    except Exception as e:
        print(f"解码失败: {e}")
        return None

def search_drop_table(lines, search_id):
    """搜索特定掉落表ID"""
    found = False
    for line in lines:
        cols = line.split('\t')
        if cols and cols[0] == search_id:
            print(f"\n找到掉落表 {search_id}:")
            for i, col in enumerate(cols):
                print(f"  列 {i}: {col}")
            found = True
            break
    if not found:
        print(f"未找到掉落表 ID: {search_id}")
    return found

if __name__ == "__main__":
    lines = decode_drop_table()
    
    # 演示：搜索双蟾纳宝的掉落表 70013
    if lines:
        print("\n" + "="*60)
        print("示例搜索: 掉落表 70013 (双蟾纳宝)")
        print("="*60)
        search_drop_table(lines, "70013")
