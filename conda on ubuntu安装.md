在 Ubuntu（含 WSL）安装 Conda 推荐使用 Miniconda，步骤如下（参考 Miniconda 官方文档：https://docs.conda.io/projects/miniconda/en/latest/）：

1. **更新系统并安装基础工具**  
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y wget bzip2
   ```

2. **下载对应架构的 Miniconda 安装脚本**  
   ```bash
   cd /tmp
   wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
   ```
   若需其他版本或架构，可从官方页面选择对应链接。

3. **（可选）校验文件完整性**  
   官方页面会给出 SHA256 校验值，可执行：  
   ```bash
   sha256sum Miniconda3-latest-Linux-x86_64.sh
   ```
   对比输出与官网提供的哈希，确认文件未损坏。

4. **运行安装脚本**  
   ```bash
   bash Miniconda3-latest-Linux-x86_64.sh
   ```
   - 按提示阅读并同意许可条款（输入 `yes`）。  
   - 选择安装路径，默认 `~/miniconda3` 即可。  
   - 安装结束时建议选择自动向 `~/.bashrc` 写入初始化代码（`conda init`），方便后续使用。
ye
5. **激活 shell 初始化**  
   如果上一步选择了自动写入，可以直接执行：  
   ```bash
   source ~/.bashrc
   ```
   若未自动初始化，可手动运行：  
   ```bash
   ~/miniconda3/bin/conda init
   source ~/.bashrc
   ```

6. **验证安装**  
   ```bash
   conda --version
   ```
   正常输出版本号即表示安装成功。

7. **配置国内镜像（可选）**  
   ```bash
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
   conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free
   conda config --set show_channel_urls yes
   ```

完成后即可在 Ubuntu/WSL 里执行 README 中的 
conda create -n deepanalyze python=3.12
conda activate deepanalyze
 等命令，搭建 DeepAnalyze 所需环境。


-------------
 在 Ubuntu/WSL 中解压 GitHub 下载的 `DeepAnalyze-main.zip`，可按以下步骤操作（假设当前在保存 zip 的目录）：

wget -O DeepAnalyze-main.zip https://codeload.github.com/tangdazhu/DeepAnalyze/zip/refs/heads/main


1. **确认已安装 unzip**
   ```bash
   
   sudo apt install -y unzip
   ```

2. **解压缩文件**
   ```bash
   unzip DeepAnalyze-main.zip
   ```
   - 若需要解压到指定目录，可用 `-d` 参数，例如：
     ```bash
     unzip DeepAnalyze-main.zip -d ~/projects
     ```

3. **进入解压后的目录**
   ```bash
   cd DeepAnalyze-main
   ```
   之后即可继续执行 README 中的环境配置、依赖安装等命令。

如果 zip 是在 Windows 侧下载的，也可以在资源管理器中右键“全部解压”到某个目录，然后在 WSL 中通过 `cd /mnt/d/...` 访问。但建议在 WSL 内直接下载和解压，避免跨盘权限问题。

----

1. 安装git-xget
pip install "huggingface_hub<1.0"

