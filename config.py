import os
from dotenv import load_dotenv
load_dotenv()

# LLM 路由配置
LLM_PROVIDER = "minimax"  # 可选: "deepseek" | "minimax" | "kimi" | "glm"

# 复杂任务模型（重要度提取、L2 规律、重排序、soul 证据检查）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

MINIMAX_MODEL = "minimax-m2.7-highspeed"
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"

KIMI_MODEL = ""
KIMI_BASE_URL = ""

GLM_MODEL = "glm-5.1"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# 简单任务模型（情绪检测、对话生成）
CHAT_MODEL = "deepseek-chat"
CHAT_BASE_URL = "https://api.deepseek.com"

# 向量嵌入模型
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
EMBEDDING_DIM = 1024           # 向量维度

# 衰减配置
DECAY_BASE_RATE = 0.95         # 每次衰减的基础比率，值越小遗忘越快
DECAY_DAMPING_FACTOR = 0.6     # 衰减阻尼系数，值越大衰减越慢
DECAY_INTERVAL_DAYS = 1        # 衰减任务执行间隔（天）
DORMANT_THRESHOLD = 0.3        # decay_score 低于此值进入 dormant 休眠状态
ARCHIVE_THRESHOLD = 0.1        # decay_score 低于此值归档（archived）

# 记忆图配置
GRAPH_BUILD_EDGE_TOP_N = 50                   # 建图时每个节点最多保留的邻边数
GRAPH_BUILD_EDGE_SIMILARITY_THRESHOLD = 0.6   # 建图时创建边的最低相似度阈值
GRAPH_RETRIEVAL_STRENGTHEN_INCREMENT = 0.1    # 每次检索后共现边强度的增量
GRAPH_RETRIEVAL_EXPAND_MIN_STRENGTH = 0.3     # 图扩展时纳入邻居节点的最低边强度
GRAPH_DORMANT_REVIVAL_NEIGHBOR_COUNT = 3      # 休眠记忆复活时参考的邻居数
GRAPH_DORMANT_REVIVAL_RECENT_DAYS = 7         # 复活时考虑的近期活跃天数
GRAPH_EDGE_DECAY_RATE = 0.99                  # 边强度的每日衰减率

# 情绪峰值触发
EMOTION_SNAPSHOT_THRESHOLD = 0.7   # emotion_intensity 超过此值时保存情绪快照

# is_derivable 过滤
IS_DERIVABLE_DISCARD_THRESHOLD = 0.8   # 可推导分超过此值则丢弃该事件（避免存储常识）

# L2 规律引擎配置
L2_IMPORTANCE_SUM_THRESHOLD = 10.0     # 同话题 importance 累积达到此值才触发抽象
L2_IMPORTANCE_SUM_THRESHOLD_SEED = 3.0 # 种子初始化通路的较低阈值（事件少、importance 低）
L2_ABSTRACTED_IMPORTANCE_DECAY = 0.5   # 事件被抽象进某个 pattern 后，其 importance × 此值
L2_INITIAL_CONFIDENCE = 0.6            # 新规律的初始置信度
L2_CONFIDENCE_INCREMENT = 0.1          # 每次 reinforce 时置信度的增量
L2_SOUL_CONTRIBUTION_THRESHOLD = 0.8   # 规律置信度超过此值才向 soul 缓变区贡献积分

# Soul 配置
SOUL_EVIDENCE_DECAY_RATE = 0.98    # soul 缓变区证据分的每日衰减率
SOUL_ANCHOR_MAX_TOKENS = 10000     # soul anchor 摘要文本的最大 token 数（阶段一：不做裁剪）

# 容量限制
L1_MAX_ACTIVE = 2000      # L1 最多保留的 active 事件数
L2_MAX_PATTERNS = 200     # L2 最多保留的 active 规律数

LOG_LEVEL = "INFO"

# LLM 输出上限（当前 DeepSeek-chat 硬限 8192；换模型时一处改）
LLM_MAX_OUTPUT_TOKENS = 8192

# 访谈通路：字段 confidence 低于此值不写入 soul.json（进"回访建议"）
INTERVIEW_CONFIDENCE_THRESHOLD = 0.5
