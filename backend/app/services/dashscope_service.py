import json
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import AsyncGenerator
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.services.local_rag_service import embed_texts_local, rerank_similarity_pairs_local

_LESSON_PLAN_TEMPLATE_CACHE: str | None = None

_PROMPT_OUTLINE = """你是一位资深的大学课程设计专家，熟悉中国高校课程教学大纲的编写规范。请根据以下课程信息和知识库内容，生成一份符合中国高校标准的课程教学大纲。

## 输出要求

1. 严格按照下方【示例】的结构和格式输出
2. 使用 Markdown 格式
3. 内容要专业、准确、有层次，符合中国高校教学大纲规范
4. 如果知识库内容不足，请基于课程名称和学时合理推断并补充内容
5. 教学目标需对应毕业要求指标点
6. 课程教学内容需包含：教学内容、学时、学习达成、课外环节、支撑课程目标、教学方法、思政案例名称
7. 课程考核需包含：考核内容和成绩组成表、评分标准
8. 直接输出大纲，不要输出多余的解释

## 课程信息

课程名称：{course_name}
学时：{hours}
课程简介：{course_description}

## 知识库（已结构化的课程知识点，至多3级层次）

{material_content}

## 示例（请参考以下格式和结构）

《统计学B》课程教学大纲

一、基本信息

| 项目 | 内容 |
|------|------|
| 课程名称（中文） | 统计学B |
| 课程名称（英文） | Statistics B |
| 课程代码 | 19211176 |
| 开课单位 | 经济与管理学院 |
| 课程平台 | 学科教育 |
| 课程性质 | 选修 |
| 课程（群）团队 | 经济分析方法论 |
| 考核方式 | 考试 |
| 学分 | 3 |
| 授课语言 | 中文 |
| 学时 | 48（理论48 / 上机0 / 实验0 / 实践0） |
| 适用专业 | 物流管理 |
| 先修课程 | 线性代数、概率论与数理统计C、运筹学A |

课程简介：
《统计学B》是物流管理专业的一门专业选修课程，主要阐述应用统计的学科内容。课程内容包括六部分：1.统计调查与整理；2.统计指标的类型及应用；3.抽样调查；4.时间序列的编制和分析；5.统计指数的计算和应用；6.相关分析和回归分析。
课程教学主要采用线上线下混合式教学，课前要求学生预习教师指定的在线资源；课程中主要采取讲练结合的方式，在每个知识点的讲解后由学生在学习通上进行练习，教师根据练习结果实时调整讲解重点；课后教师布置统计调查实践问题，由学生分小组（2-3名学生为一组）完成，并计入平时成绩。
课程要求学生学习该课程后，能在统计工作中遵循统计工作的四条基本规范，尤其是真实性原则规范；能针对特定需要，设计统计调查方案，进行统计调查，并整理得到规范的统计表，计算统计结果的抽样平均误差并进行假设检验；能根据统计原始数据设计并计算统计指标和动态指标，并进行因素分析；能进行两个变量的相关分析和回归分析。

教材与参考资料：
1.《统计学原理》，李洁明、祁新娥 著，复旦大学出版社，2021 年，上海市精品课程教材

在线教学资源：
1. https://space.bilibili.com/319986332/channel/seriesdetail?sid=1532109

二、教学目标

| 教学目标 | 支撑毕业要求指标点 |
|----------|-------------------|
| 1. 能记住统计工作中遵循统计工作的四条基本规范，尤其是真实性原则规范。 | 6（职业规范）：具有较强的职业认同感、社会责任感，理解专业领域相关的社会、文化、健康、安全、法律、环境等问题；具有良好的身体素质和人文社会科学素养，能够在物流管理实践中理解并遵守职业道德和规范，履行工作和社会责任。 |
| 2. 能针对特定需要，设计统计调查方案，进行统计调查，并整理得到规范的统计表，计算统计结果的抽样平均误差并进行假设检验。 | 5.2（研究与创新）：通过敏锐的洞察力，能够发现、辨析、质疑、评价本专业及相关领域现象和问题，掌握创新创业的技能，具备理论联系实际，进行理论与实践的创新能力。 |
| 3. 能根据统计原始数据设计并计算统计指标和动态指标。 | 5.1（研究与创新）：能够从科学原理出发，采用科学方法对复杂物流管理问题进行研究，理论联系实际，掌握问题建模和实验仿真方法，分析与解释数据，并通过实验与实践多重验证，得到合理有效的结论。 |
| 4. 能利用统计指数、相关分析和回归分析对宏观、微观经济发展问题进行分析。 | 5.1（研究与创新）：能够从科学原理出发，采用科学方法对复杂物流管理问题进行研究，理论联系实际，掌握问题建模和实验仿真方法，分析与解释数据，并通过实验与实践多重验证，得到合理有效的结论。 |

三、课程教学内容和方法

（一）教学内容和要求

| 内容与进度 | 教学内容 | 学时 | 学习达成 | 课外环节 | 支撑课程目标 | 教学方法 | 思政案例名称 |
|-----------|---------|------|---------|---------|-------------|---------|-------------|
| 1. 统计学概述<br>（1）统计学的性质和特点<br>（2）统计工作过程<br>（3）统计学中的基本概念<br><br>重点：统计基本概念和工作规范 | 2 | 能记住统计工作的四条基本规范；能复述统计工作过程；能记住统计学研究的基本过程 | 课后作业 | 目标1 | 讲授法 | 祖国统计事业快速发展 |
| 2. 统计调查过程<br>（1）统计调查方案<br>（2）统计调查形式<br><br>重点：几种不同统计形式应用场景<br>难点：统计调查问卷的设计 | 4 | 能针对特定需要，设计统计调查方案，进行统计调查 | 课前预习教学内容/进行统计调查大作业 | 目标2 | 翻转课堂 | 祖国统计工作严谨进行 |
| 3. 统计数据整理<br>（1）统计分组与分配数列<br>（2）统计表设计<br><br>重点：统计分组、分配数列的原则和统计表设计的规范 | 4 | 能够根据实际统计数据特征对数据进行整理 | 进一步完成统计调查大作业 | 目标2 | 混合式教学 | 党领导消除贫困 |
| 4. 统计综合指标<br>（1）总量指标<br>（2）相对指标<br>（3）平均指标<br>（4）变异指标<br><br>重点：各种统计指标的作用和计算原理<br>难点：相似统计指标之间的辨析 | 6 | 能根据实际使用正确的统计指标进行问题分析 | 课后作业 | 目标3 | 混合式教学 | 建设祖国正当时 |
| 5. 抽样调查方案设计<br>（1）抽样调查的特点和作用<br>（2）抽样调查的方案设计<br><br>重点：抽样调查的本质特征、不同抽样方案的应用场景 | 2 | 能辨别几种不完备调查的异同点；能复述常见的统计调查方案；能设计抽样调查方案 | 课后观看在线教学资料 | 目标2 | 发现式教学 | 国民素质显著提高 |
| 6. 抽样调查计算问题<br>（1）抽样平均误差的概念与计算<br>（2）抽样所需样本量的计算<br>（3）总体参数的估计和检验<br><br>重点：平均抽样误差的计算、总体参数的区间估计、总体参数的假设检验<br>难点：假设检验的原理的精确理解 | 6 | 能够根据要求精度计算抽样所需样本数；能够根据抽样调查结果对总体进行正确判断 | 课后作业 | 目标2 | 混合式教学 | 真实性是统计工作的第一要求 |
| 7. 动态数列基础<br>（1）动态数列的编制<br>（2）动态数列指标的设计和计算<br><br>重点：动态数列指标的应用场景和计算方式 | 4 | 能正确编制动态数列并计算和使用动态数列指标 | 课后作业 | 目标3 | 混合式教学 | 祖国经济高速发展 |
| 8. 动态数列建模<br>（1）动态数列趋势测定<br>（2）动态数列季节变动测定<br><br>重点：测定动态数列的趋势和季节变动 | 4 | 能建立正确的动态数列分析模型 | 课后观看在线教学资料 | 目标3 | 混合式教学 | 人民生活水平高速发展 |
| 9. 个体指数和总指数<br>（1）统计指数的定义和作用<br>（2）个体指数的计算方法<br>（3）通过综合指数计算总指数的方法<br>（4）通过平均指数计算总指数的方法<br><br>重点：总指数的定义和计算方式<br>难点：总指数计算时通度量因素的选择方式 | 4 | 能正确回答统计指数的作用；能正确计算总指数；能根据实际问题设计适当的指数 | 统计指数大作业/观看在线教学资料 | 目标4 | 发现式教学 | 政府如何平抑通胀 |
| 10. 因素分解法<br>（1）二因素的因素分解分析法<br>（2）基于因素分解法构建平均指标对比指数<br><br>重点：因素分析法的计算过程 | 4 | 能正确使用因素分解法分解总指数和可变构成指数 | 继续完成统计指数大作业 | 目标4 | 混合式教学 | 从统计指数阅读国家工业发展 |
| 11. 相关分析与回归分析<br>（1）相关分析的概念和线性相关分析的计算<br>（2）回归分析的概念和线性回归分析的计算<br><br>重点：变量相关的形式、相关分析的和回归分析的异同、线性相关系数和回归系数的计算方法<br>难点：线性相关系数和回归系数的计算的原理 | 8 | 能够回答相关分析和回归分析的应用场景、能回答线性相关系数和回归系数含义；能够使用Excel软件进行线性相关分析和回归分析 | 课后作业/复习全课程所学内容 | 目标4 | 混合式教学 | 正确看待民营资本在经济发展中的重要作用 |

（二）教学方法

讲授法：按照预定教案讲述课程内容，运用于第一堂课课程概述；

翻转课堂：由学生事先预先教学内容，分组进行讲解，之后由教师进行点评和补充；

混合式教学：结合线上（学习通）线下教学方式进行教学，是本课程的主要教学方式，利用线下教学方式进行内容讲解，并利用线上方式实时进行课堂互动、课堂讨论、课堂练习，教师实时根据学习通的分析结果发现学生学习过程中的问题并进行实时调整；

发现式教学：基于布鲁纳的发现学习理论，通过实例引导学生重新发现课程所要学习的知识，有利于培养学生的创新能力和综合能力，支撑毕业目标。

四、课程考核及成绩评定

（一）考核内容和成绩组成

课程考核以考核学生能力培养目标的达成为主要目的，以考查学生对基于应用统计学方法解决复杂问题的能力为重要内容，包括平时考核(60%)和期末考核(40%)两部分。平时考核包括课后作业、分组大作业、平时成绩(课堂出勤、课堂测验、主题讨论、在线学习等)三个部分。期末考核采用闭卷笔试。

各课程目标对应的考核内容、成绩比例组成如下：

| 考核方式与权重 | 考核环节 | 目标1 | 目标2 | 目标3 | 目标4 |
|--------------|---------|-------|-------|-------|-------|
| 平时成绩 20% | | 20% | 30% | 30% | |
| 分组大作业 | | | 50% | | 50% |
| 考试 | | 10% | 35% | 35% | 20% |
| 课后作业 | | 10% | 30% | 30% | 30% |
| 总权重 | | 40% | 135% | 95% | 130% |

总成绩 = 平时作业×20% + 分组大作业×20% + 考试×40% + 课后作业×20%

（二）评分标准

（1）平时成绩：支撑课程目标1、2、3、4，根据学习通的学习数据评分，其中课程出勤30%，参与讨论20%，课中测验和讨论50%，总评后折算成 20 分。

（2）课后作业：支撑课程目标1、2、3、4，每次作业必须在规定时间点前交，迟交作业或作业不满足要求，均以零分计。每次作业按百分制评分，总评后折算成 20 分。

| 完成情况 | 得分 |
|---------|------|
| 严格按照作业要求并及时完成，基本概念清晰，解决问题的方案正确、合理，计算方法正确，计算过程清楚，符合规范要求，能提出不同的解决方案。 | 90-100 分 |
| 严格按照作业要求并及时完成，基本概念较清晰，解决问题的方案比较合理，计算方法比较正确，计算过程比较清楚，符合规范要求。 | 80-90 分 |
| 基本按照作业要求并及时完成，基本概念基本清晰，解决问题的方案基本正确、基本合理，计算方法基本正确，基本符合规范要求。 | 60-79 分 |
| 不能按照作业要求，未及时完成，基本概念不清晰，解决问题的方案基本不正确、不合理，计算方法基本不正确，基本不符合规范要求。 | 40-59 分 |
| 不能按照作业要求，未及时完成，基本概念不清晰，不能制定正确和合理解决问题的方案，计算方法不正确，不符合规范要求。 | 0-39 分 |

（3）分组大作业：支撑课程目标2、4，必须在规定时间点前交，迟交作业或作业不满足要求，均以零分计，总评后折算成 20 分。具体评分标准参考第（2）点中的作业评分表。

（4）考试：支撑课程目标1、2、3、4，按期终考试的标准答案、评分标准百分制评分，总评后折算成 40 分。

---

请根据以上示例的格式和结构，为课程「{course_name}」生成课程教学大纲。
"""

_PROMPT_CLASSIFY = """判断以下文档片段的复杂程度，只输出一个 JSON。

分类标准：
- multi_chapter：包含多个独立章节/大节，有明显多级层次（如教材、完整课件）
- single_chapter：仅单个章节或单一主题块，内部有小节但不跨越多个独立章节
- flat：无明显章节结构，仅为连续内容片段

只输出如下 JSON，禁止其他文本：
{{"complexity":"multi_chapter 或 single_chapter 或 flat"}}

文档片段：
{content}
"""

_PROMPT_MULTI_CHAPTER = """你是一位课程资料结构化专家。这是一份多章节文档，请生成结构化摘要卡片。

要求：
1) 只输出一个 JSON 对象，禁止 Markdown 和解释性文本
2) 字段必须完整，不得增删改
3) keywords 固定 5 个短语，去重
4) structure 输出 3-10 个节点，section 保留原文章号（如"第一章 函数与极限"）
5) 每个 key_points 输出 2-4 条简短短句
6) summary 为 4-6 句，强调课程可用信息
7) 每个 structure 节点必须包含 first_sentence 和 last_sentence：
   - first_sentence：该章节正文的第一句原文原话（逐字复制，不得改写）
   - last_sentence：该章节正文的最后一句原文原话（逐字复制，不得改写）
8) 如果某章节正文过短（少于2句），first_sentence 和 last_sentence 可以相同

输出 schema（严格按此格式）：
{{
  "version": "v1",
  "complexity": "multi_chapter",
  "title": "文档标题",
  "document_type": "教材|课件|论文|实验指导|政策文件|其他",
  "summary": "4-6 句摘要",
  "keywords": ["kw1","kw2","kw3","kw4","kw5"],
  "structure": [
    {{
      "section": "章节标题（含章号）",
      "first_sentence": "该章节正文第一句原话",
      "last_sentence": "该章节正文最后一句原话",
      "key_points": ["要点1","要点2"]
    }}
  ],
  "teaching_value": "该文档对教学的作用",
  "granularity_hint": "balanced"
}}

再次强调：first_sentence 和 last_sentence 必须是原文原句的逐字复制，不得改写、不得省略、不得意译。这两句将用于程序自动定位章节边界。

文档内容（Markdown）：
{content}
"""

_PROMPT_SINGLE_CHAPTER = """你是一位课程资料结构化专家。这是一份单章节文档，请生成结构化摘要卡片。

要求：
1) 只输出一个 JSON 对象，禁止 Markdown 和解释性文本
2) 字段必须完整，不得增删改
3) keywords 固定 5 个短语，去重
4) chapter_title 为本章节的完整标题（含章号，如"第三章 导数与微分"）
5) structure 输出 2-6 个节点，描述本章节内部的知识点或小节
6) 每个 key_points 输出 2-4 条简短短句
7) summary 为 3-5 句

输出 schema：
{{
  "version": "v1",
  "complexity": "single_chapter",
  "title": "文档标题",
  "chapter_title": "当前章节的完整标题（含章号）",
  "document_type": "教材|课件|论文|实验指导|政策文件|其他",
  "summary": "3-5 句摘要",
  "keywords": ["kw1","kw2","kw3","kw4","kw5"],
  "structure": [
    {{"section": "小节或知识点名称", "key_points": ["要点1","要点2"]}}
  ],
  "teaching_value": "该文档对教学的作用",
  "granularity_hint": "single"
}}

文档内容（Markdown）：
{content}
"""

_PROMPT_FLAT = """你是一位课程资料结构化专家。这是一段无明显章节结构的连续内容，请生成摘要卡片。

要求：
1) 只输出一个 JSON 对象，禁止 Markdown 和解释性文本
2) 字段必须完整，不得增删改
3) keywords 固定 5 个短语，去重
4) title 为你概括的主题名称，不带章号
5) key_points 输出 3-5 条核心要点，使用简短短句
6) 不输出 structure 字段
7) summary 为 2-4 句

输出 schema：
{{
  "version": "v1",
  "complexity": "flat",
  "title": "为内容拟定的标题（无章号）",
  "document_type": "教材|课件|论文|实验指导|政策文件|其他",
  "summary": "2-4 句摘要",
  "keywords": ["kw1","kw2","kw3","kw4","kw5"],
  "key_points": ["核心要点1","核心要点2","核心要点3"],
  "teaching_value": "该文档对教学的作用",
  "granularity_hint": "flat"
}}

文档内容（Markdown）：
{content}
"""

_PROMPT_CHAPTER_KNOWLEDGE = """你是一位高校课程知识建模专家。请对一个章节提取知识点（第一轮主抽取），仅输出 JSON 对象。

任务目标：
1) 识别本章节核心知识点
2) 给出每个知识点的子知识点列表
3) 给出每个知识点的一句话描述
4) 给出每个子知识点的一句话描述（用于入库展示）

要求：
1) 只输出一个 JSON 对象，禁止 Markdown 和解释文本
2) 知识点名称短而准确，避免同义重复
3) points 数量建议 6-14，尽量覆盖定义、原理、方法、应用、边界条件
4) sub_points 只写直接子知识点，不要写完整树
5) description 使用课程语境下的定义/作用说明，1-2句。若原文无描述或描述极少（如PPT仅列标题），应基于你的学科知识补充合理的教学定义，使描述具备教学可用性
6) sub_point_descriptions 的 key 必须来自 sub_points，value 为 1 句定义/作用说明。同样允许在原文缺失时基于知识补充
7) 优先忠实原文；若原文存在公式转写损坏、PPT短句不完整、语序破碎等问题，可在不新增知识点的前提下，对 description 与 sub_point_descriptions 做最小必要的格式化修复与语言补全
8) 禁止凭空新增原文中不存在的新知识点、新子知识点或新结论；仅允许在保持知识点实体不变的前提下，补全或优化其描述文本，使其达到可直接用于教案编写的完整度

输出 schema：
{{
  "points": [
    {{
      "knowledge_point": "知识点名称",
      "sub_points": ["子知识点1", "子知识点2"],
      "description": "该知识点的定义或作用说明",
      "sub_point_descriptions": {{
        "子知识点1": "子知识点1的定义或作用说明",
        "子知识点2": "子知识点2的定义或作用说明"
      }}
    }}
  ]
}}

章节标题：
{section}

章节内容（Markdown）：
{content}
"""

_PROMPT_CHAPTER_KNOWLEDGE_SUPPLEMENT = """你是一位高校课程知识建模专家。请执行“补漏抽取”，仅输出 JSON 对象。

任务目标：
1) 已有一批知识点，请识别章节中仍未覆盖的重要知识点
2) 仅补充缺失项，避免重复和同义改写

要求：
1) 只输出一个 JSON 对象，禁止 Markdown 和解释文本
2) missing_points 数量 0-6；若无缺失，返回空数组
3) 每个字段与主抽取一致：knowledge_point、sub_points、description、sub_point_descriptions
4) 不输出已有知识点或其同义改写
5) 补充项应尽量忠实原文；若原文表达残缺，可仅在描述字段做最小必要的语言补全，不得引入新的知识点实体

输出 schema：
{{
  "missing_points": [
    {{
      "knowledge_point": "知识点名称",
      "sub_points": ["子知识点1", "子知识点2"],
      "description": "该知识点的定义或作用说明",
      "sub_point_descriptions": {{
        "子知识点1": "子知识点1的定义或作用说明"
      }}
    }}
  ]
}}

章节标题：
{section}

已有知识点：
{existing_points}

章节内容（Markdown）：
{content}
"""

_PROMPT_KNOWLEDGE_RELATION_DECISION = """你是一位课程知识图谱专家。请根据当前知识点与候选列表，判断其前置、后置、关联知识点。

判定定义：
1) 前置知识点：学习当前知识点前通常需要先掌握的知识
2) 后置知识点：通常在掌握当前知识点后再学习的知识
3) 关联知识点：与当前知识点强相关，但不一定有严格先后关系

要求：
1) 仅输出 JSON 对象，禁止解释文本
2) 只能从候选列表中选择
3) 三类结果各自去重
4) 每类最多 5 个
5) 不要把当前知识点自身放入结果

输出 schema：
{{
  "prerequisite_points": ["知识点A", "知识点B"],
  "postrequisite_points": ["知识点C"],
  "related_points": ["知识点D"]
}}

当前知识点名称：
{name}

当前知识点路径：
{path}

当前知识点描述：
{description}

前置候选：
{prereq_candidates}

后置候选：
{post_candidates}

关联候选：
{related_candidates}
"""

_PROMPT_KNOWLEDGE_RELATION_DECISION_BATCH = """你是一位课程知识图谱专家。请对一批知识点同时判定关系，并识别同义/重复概念。

判定定义：
1) 前置知识点：学习当前知识点前通常需要先掌握的知识
2) 后置知识点：通常在掌握当前知识点后再学习的知识
3) 关联知识点：与当前知识点强相关，但不一定有严格先后关系
4) 重复知识点：语义等价或同义概念，教材中可跨章节重复出现

要求：
1) 仅输出 JSON 对象，禁止解释文本
2) 每个知识点只能从它自身候选列表中选择
3) 三类关系各自去重，每类最多 5 个
4) duplicate_points 最多 3 个
5) 不得把当前知识点自身放入任何结果

输出 schema：
{{
  "items": [
    {{
      "id": "kp_xxx",
      "prerequisite_points": ["知识点A"],
      "postrequisite_points": ["知识点B"],
      "related_points": ["知识点C"],
      "duplicate_points": ["知识点D"]
    }}
  ]
}}

待判定知识点列表（JSON）：
{items_json}
"""


def build_outline_prompt(
    course_name: str,
    hours: str,
    material_content: str,
    course_description: str = "",
    strategy_content: str = "",
    user_guidance: str = "",
) -> str:
    prompt = _PROMPT_OUTLINE.format(
        course_name=course_name, hours=hours, material_content=material_content,
        course_description=course_description or "（暂无课程简介）"
    )
    if strategy_content:
        prompt += f"\n\n## 第一阶段教学设计策略\n\n{strategy_content}\n"
    if user_guidance:
        prompt += f"\n\n## 教师补充方向\n\n{user_guidance}\n"
    prompt += "\n\n请在充分吸收第一阶段策略与教师补充方向的基础上，输出最终课程教学大纲。"
    return prompt


def build_generation_strategy_prompt(
    output_type: str,
    course_name: str,
    hours: str,
    course_description: str,
    knowledge_content: str,
    user_guidance: str = "",
) -> str:
    return f"""你是一位高校课程设计顾问。请先不要直接生成最终文稿，而是先为课程产出一份“教学设计策略”。

你的任务是根据课程基本信息、知识库和教师补充方向，分析这门课更适合采用哪些教学理念、方法和组织方式。

可参考但不限于以下理念与方法：
- OBE / 成果导向教育
- 布鲁姆教育目标分类学
- PBL / 项目式学习
- BOPPPS
- ISW
- 翻转课堂
- 混合式教学
- 案例教学
- 情境教学
- 探究式学习
- 任务驱动
- 协作学习

请只输出 Markdown，结构严格如下：

# 教学设计策略
## 课程定位
- 课程定位：
- 学习者特点：
- 核心能力目标：

## 教学理念与方法
- 建议采用的理念：
- 建议采用的教学方法：
- 这些方法适配本课程的原因：

## 教学组织建议
- 教学组织形式：
- 理论与实践比例建议：
- 课堂活动建议：
- 课外学习建议：

## 评价与达成建议
- 过程性评价建议：
- 终结性评价建议：
- 课程目标达成证据：

## 本次生成重点
- 面向“{output_type}”应重点强调的内容：
- 写作风格建议：
- 应避免的问题：

课程名称：{course_name}
学时：{hours}
课程简介：{course_description or '（暂无课程简介）'}

教师补充方向：
{user_guidance or '（教师未额外填写）'}

课程知识库：
{knowledge_content}
"""


def build_artifact_prompt(
    output_type: str,
    course_name: str,
    hours: str,
    course_description: str,
    knowledge_content: str,
    strategy_content: str,
    user_guidance: str = "",
    lesson_plan_instruction: str = "",
    outline_reference: str = "",
) -> str:
    output_label_map = {
        "outline": "课程教学大纲",
        "teaching_plan": "教学计划",
        "lesson_plan": "教案设计",
        "ideology_case": "思政案例设计",
        "knowledge": "课程知识库文档",
    }
    output_label = output_label_map.get(output_type, output_type)
    special_requirements = {
        "outline": """请严格参考示例结构输出，至少包含：基本信息、课程简介、教学目标、教学内容和方法、课程考核及成绩评定。""",
        "teaching_plan": """请输出可直接用于学期实施的教学计划，至少包含：总体安排、周次/课次安排表、教学重点难点、教学活动设计、考核安排、资源建议。""",
        "lesson_plan": """请输出可直接上课使用的教案设计，至少包含：课题、学情分析、教学目标、重难点、教学准备、教学过程、板书设计、作业与反思。""",
        "ideology_case": """请输出课程思政案例方案，至少包含：案例主题、融入知识点、育人目标、教学实施步骤、课堂互动问题、评价方式、风险提醒。""",
        "knowledge": """请输出课程知识库文档，至少包含：课程知识体系总览、按章节组织的知识点树、关键概念解释、前置/后置/关联知识说明、学习建议。""",
    }
    template_reference = ""
    if output_type == "lesson_plan":
        template_reference = _load_lesson_plan_template_reference()
    prompt = f"""你是一位高校课程内容生成专家。请根据课程信息、结构化知识库、教师补充方向以及前一阶段生成的“教学设计策略”，生成最终的“{output_label}”。

要求：
1. 直接输出最终 Markdown 成果，不要输出解释
2. 充分吸收“教学设计策略”，体现恰当的教育理念与教学方法
3. 既要使用课程已有知识库，也要结合课程学时与课程简介进行合理补充
4. 内容要专业、完整、可执行，面向高校真实教学场景
5. 对于表格内容，优先使用 Markdown 表格

该类型的专属要求：
{special_requirements.get(output_type, '请生成专业、结构完整的教学文稿。')}

课程名称：{course_name}
学时：{hours}
课程简介：{course_description or '（暂无课程简介）'}

教师补充方向：
{user_guidance or '（教师未额外填写）'}

教学设计策略：
{strategy_content}

课程知识库：
{knowledge_content}
"""
    if template_reference:
        prompt += f"\n\n教案模板参考（来自 external_material/教案设计模板.docx）：\n{template_reference}"
    if lesson_plan_instruction:
        prompt += f"\n\n本次教案任务约束：\n{lesson_plan_instruction}"
    if outline_reference:
        prompt += f"\n\n可参考的既有课程大纲：\n{outline_reference}"
    return prompt


def _load_lesson_plan_template_reference() -> str:
    global _LESSON_PLAN_TEMPLATE_CACHE
    if _LESSON_PLAN_TEMPLATE_CACHE is not None:
        return _LESSON_PLAN_TEMPLATE_CACHE
    template_path = Path(__file__).resolve().parents[3] / "external_material" / "教案设计模板.docx"
    if not template_path.exists():
        _LESSON_PLAN_TEMPLATE_CACHE = ""
        return _LESSON_PLAN_TEMPLATE_CACHE
    try:
        with zipfile.ZipFile(template_path) as zf:
            xml_data = zf.read("word/document.xml")
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ET.fromstring(xml_data)
        lines: list[str] = []
        for para in root.findall(".//w:p", ns):
            text = "".join((node.text or "") for node in para.findall(".//w:t", ns)).strip()
            if not text:
                continue
            normalized = re.sub(r"\s+", " ", text)
            if normalized in lines:
                continue
            lines.append(normalized)
            if len(lines) >= 80:
                break
        if not lines:
            _LESSON_PLAN_TEMPLATE_CACHE = ""
            return _LESSON_PLAN_TEMPLATE_CACHE
        preferred = [
            "课题名称",
            "授课学时",
            "授课对象",
            "授课地点",
            "使用教材及出版单位",
            "授课类型",
            "信息技术资源",
            "教学设计思想",
            "教材分析",
            "学情分析",
            "教学目标",
            "教学重点",
            "教学难点",
            "教学方法",
            "教学过程",
            "主要步骤",
            "教师活动",
            "学生活动",
            "设计意图",
            "活动时间及资源准备",
            "作业布置",
            "板书设计",
            "课后反思",
            "备注",
        ]
        catalog = [item for item in preferred if any(item in line for line in lines)]
        template_lines = ["请遵循以下模板要素组织教案，允许按课程特点适度扩展："]
        for item in catalog:
            template_lines.append(f"- {item}")
        template_lines.append("教学过程需按“步骤-教师活动-学生活动-设计意图-时间与资源”对应展开。")
        template_lines.append("保持教-学-评一致，突出重点、难点与突破策略。")
        _LESSON_PLAN_TEMPLATE_CACHE = "\n".join(template_lines)
        return _LESSON_PLAN_TEMPLATE_CACHE
    except Exception as exc:
        logger.warning("读取教案模板失败 | path={} | err={}", template_path, exc)
        _LESSON_PLAN_TEMPLATE_CACHE = ""
        return _LESSON_PLAN_TEMPLATE_CACHE


def _resolve_llm_provider() -> str:
    provider = (settings.llm_provider or "dashscope").strip().lower()
    if provider in ("deepseek", "dashscope", "openrouter"):
        return provider
    return "dashscope"


def _resolve_llm_endpoint_and_key() -> tuple[str, str]:
    provider = _resolve_llm_provider()
    if provider == "deepseek":
        return settings.deepseek_base_url, settings.deepseek_api_key
    if provider == "openrouter":
        return settings.openrouter_base_url, settings.openrouter_api_key
    return settings.dashscope_base_url, settings.dashscope_api_key


def _resolve_default_chat_model() -> str:
    provider = _resolve_llm_provider()
    if provider == "deepseek":
        return settings.deepseek_model
    if provider == "openrouter":
        return settings.openrouter_model
    return settings.dashscope_model


def _build_provider_error(provider: str, response: httpx.Response) -> str:
    status = response.status_code
    request_id = response.headers.get("x-request-id", "")
    detail = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = _as_text(err.get("message"), "")
                code = _as_text(err.get("code"), "")
                err_type = _as_text(err.get("type"), "")
                req_in_body = _as_text(data.get("request_id"), "")
                if req_in_body:
                    request_id = req_in_body
                parts = [p for p in (err_type, code, msg) if p]
                if parts:
                    detail = " | ".join(parts)
    except Exception:
        detail = ""
    if not detail:
        body = (response.text or "").strip().replace("\n", " ")
        detail = body[:400] if body else response.reason_phrase
    rid = f" | request_id={request_id}" if request_id else ""
    return f"{provider} 调用失败 | status={status}{rid} | detail={detail}"


def _ensure_success(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    raise RuntimeError(_build_provider_error(provider, response))


def _as_timeout_error(provider: str, model: str, stage: str, exc: Exception) -> RuntimeError:
    detail = str(exc).strip() or exc.__class__.__name__
    return RuntimeError(f"{provider} 调用超时 | stage={stage} | model={model} | detail={detail}")


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]")


def _append_preview_tokens(tokens: list[str], text: str, limit: int = 100) -> None:
    if not text or len(tokens) >= limit:
        return
    remain = limit - len(tokens)
    tokens.extend(_TOKEN_PATTERN.findall(text)[:remain])


def _extract_delta_content(chunk: dict[str, Any]) -> str:
    delta = chunk.get("choices", [{}])[0].get("delta", {})
    content = delta.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts)
    return ""


async def _stream_chat_response(
    prompt: str,
    model: str,
    *,
    temperature: float | None = None,
    response_format: dict[str, str] | None = None,
    stage: str,
) -> AsyncGenerator[str, None]:
    provider = _resolve_llm_provider()
    base_url, api_key = _resolve_llm_endpoint_and_key()
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format
    if provider == "openrouter":
        payload["reasoning"] = {"enabled": True}

    logger.info("{} 开始 | model={} | prompt前80字={}", stage, model, prompt[:80].replace("\n", " "))
    t0 = time.monotonic()
    chunk_count = 0
    content_len = 0
    token_preview: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(_build_provider_error(provider, resp))
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    content = _extract_delta_content(chunk)
                    if not content:
                        continue
                    chunk_count += 1
                    content_len += len(content)
                    _append_preview_tokens(token_preview, content)
                    yield content
    except httpx.TimeoutException as exc:
        raise _as_timeout_error(provider, model, stage, exc) from exc

    elapsed = time.monotonic() - t0
    logger.info(
        "{} 完成 | 耗时={:.1f}s | chunks={} | 输出长度={} | 前100token={}",
        stage,
        elapsed,
        chunk_count,
        content_len,
        " ".join(token_preview),
    )


async def stream_chat(
    prompt: str,
    model: str | None = None,
) -> AsyncGenerator[str, None]:
    model = model or _resolve_default_chat_model()
    async for content in _stream_chat_response(prompt, model, stage="stream_chat"):
        yield content


async def chat_once(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    response_format: dict[str, str] | None = None,
    stage: str = "chat_once",
) -> str:
    model = model or _resolve_default_chat_model()
    parts: list[str] = []
    async for content in _stream_chat_response(
        prompt,
        model,
        temperature=temperature,
        response_format=response_format,
        stage=stage,
    ):
        parts.append(content)
    content = "".join(parts)
    logger.info("{} 聚合完成 | 输出长度={}", stage, len(content))
    return content


async def _classify_material(content_head: str, model: str) -> str:
    prompt = _PROMPT_CLASSIFY.format(content=content_head)
    logger.info("classify_material 路由调用 | model={}", model)
    t0 = time.monotonic()
    for attempt in range(2):
        try:
            raw = await chat_once(
                prompt,
                model=model,
                temperature=0.0,
                response_format={"type": "json_object"},
                stage="classify_material",
            )
            parsed = _parse_summary_json(raw)
            complexity = _as_complexity(parsed.get("complexity"))
            elapsed = time.monotonic() - t0
            logger.info("classify_material 完成 | complexity={} | 耗时={:.1f}s", complexity, elapsed)
            return complexity
        except RuntimeError as exc:
            if attempt == 0 and "调用超时" in str(exc):
                logger.warning("classify_material 超时，重试一次 | model={} | err={}", model, exc)
                continue
            raise


async def _call_card_prompt(prompt: str, model: str) -> str:
    return await chat_once(
        prompt,
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        stage="card_prompt",
    )


async def generate_summary(markdown_content: str, model: str | None = None) -> str:
    model = model or _resolve_default_chat_model()
    content_head = markdown_content[:8000]

    complexity = await _classify_material(content_head, model)
    logger.info("generate_summary 路由结果={} | 原文长度={}", complexity, len(markdown_content))

    prompt_map = {
        "multi_chapter": _PROMPT_MULTI_CHAPTER,
        "single_chapter": _PROMPT_SINGLE_CHAPTER,
        "flat": _PROMPT_FLAT,
    }
    t0 = time.monotonic()
    last_exc: Exception | None = None
    content_caps = [18000, 12000, 9000]
    for cap in content_caps:
        content = markdown_content[:cap] if len(markdown_content) > cap else markdown_content
        prompt = prompt_map[complexity].format(content=content)
        try:
            raw = await _call_card_prompt(prompt, model)
            result = _normalize_summary_card(raw, force_complexity=complexity)
            elapsed = time.monotonic() - t0
            logger.info(
                "generate_summary 卡片生成完成 | complexity={} | content_len={} | 耗时={:.1f}s | 输出长度={}",
                complexity,
                len(content),
                elapsed,
                len(result),
            )
            return result
        except RuntimeError as exc:
            last_exc = exc
            msg = str(exc)
            if "stage=card_prompt" in msg and cap != content_caps[-1]:
                logger.warning("generate_summary 卡片阶段超时，降采样重试 | content_len={} | err={}", len(content), msg)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("generate_summary 未知错误")


def extract_chapters(summary_json: str, markdown: str) -> list[dict[str, Any]]:
    card = json.loads(summary_json)
    if card.get("complexity") != "multi_chapter":
        return []
    structure = card.get("structure", [])
    if not structure:
        return []
    chapters: list[dict[str, Any]] = []
    for idx, node in enumerate(structure):
        section = node.get("section", f"第{idx+1}章")
        first_sent = node.get("first_sentence", "").strip()
        last_sent = node.get("last_sentence", "").strip()
        content = ""
        if first_sent and last_sent:
            pattern = re.escape(first_sent) + r"(.*?)" + re.escape(last_sent)
            match = re.search(pattern, markdown, re.DOTALL)
            if match:
                content = (first_sent + match.group(1) + last_sent).strip()
        if not content and first_sent:
            pattern = re.escape(first_sent) + r"(.*?)(?=\n#{1,3}\s|\n\n##|\Z)"
            match = re.search(pattern, markdown, re.DOTALL)
            if match:
                content = match.group(0).strip()
        chapters.append({
            "chapter_index": idx,
            "section": section,
            "first_sentence": first_sent,
            "last_sentence": last_sent,
            "content": content,
            "char_count": len(content),
        })
    logger.info("extract_chapters 完成 | 提取 {} 个章节 | 有内容的: {}", len(chapters), sum(1 for c in chapters if c["content"]))
    return chapters


async def extract_chapter_knowledge_points(
    chapter_section: str,
    chapter_content: str,
    model: str | None = None,
) -> list[dict[str, Any]]:
    model = model or _resolve_default_chat_model()
    content = chapter_content[:48000] if len(chapter_content) > 48000 else chapter_content
    prompt = _PROMPT_CHAPTER_KNOWLEDGE.format(section=chapter_section, content=content)
    raw = await _call_card_prompt(prompt, model)
    parsed = _parse_summary_json(raw)
    primary = _as_knowledge_points(parsed.get("points"))
    supplement: list[dict[str, Any]] = []
    if settings.knowledge_extract_enable_supplement:
        existing_points = "\n".join(
            f"- {item['knowledge_point']}" for item in primary if item.get("knowledge_point")
        ) or "- 无"
        supplement_prompt = _PROMPT_CHAPTER_KNOWLEDGE_SUPPLEMENT.format(
            section=chapter_section,
            existing_points=existing_points,
            content=content,
        )
        supplement_raw = await _call_card_prompt(supplement_prompt, model)
        supplement_parsed = _parse_summary_json(supplement_raw)
        supplement = _as_knowledge_points(
            supplement_parsed.get("missing_points", supplement_parsed.get("points"))
        )
    merged = _merge_knowledge_points(primary, supplement)
    logger.info(
        "extract_chapter_knowledge_points 完成 | section={} | 主抽取={} | 补漏={} | 合并后={}",
        chapter_section,
        len(primary),
        len(supplement),
        len(merged),
    )
    return merged


async def infer_knowledge_relations(
    point_name: str,
    point_path: str,
    point_description: str,
    prerequisite_candidates: list[str],
    postrequisite_candidates: list[str],
    related_candidates: list[str],
    model: str | None = None,
) -> dict[str, list[str]]:
    model = model or _resolve_default_chat_model()
    prompt = _PROMPT_KNOWLEDGE_RELATION_DECISION.format(
        name=point_name,
        path=point_path,
        description=point_description,
        prereq_candidates=json.dumps(prerequisite_candidates, ensure_ascii=False),
        post_candidates=json.dumps(postrequisite_candidates, ensure_ascii=False),
        related_candidates=json.dumps(related_candidates, ensure_ascii=False),
    )
    raw = await _call_card_prompt(prompt, model)
    parsed = _parse_summary_json(raw)
    return {
        "prerequisite_points": _as_relation_list(parsed.get("prerequisite_points"), point_name),
        "postrequisite_points": _as_relation_list(parsed.get("postrequisite_points"), point_name),
        "related_points": _as_relation_list(parsed.get("related_points"), point_name),
    }


async def infer_knowledge_relations_batch(
    items: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, dict[str, list[str]]]:
    if not items:
        return {}
    model = model or _resolve_default_chat_model()
    normalized: list[dict[str, Any]] = []
    for item in items:
        point_id = _as_text(item.get("id"), "")
        point_name = _as_text(item.get("name"), "")
        if not point_id or not point_name:
            continue
        normalized.append(
            {
                "id": point_id,
                "name": point_name,
                "path": _as_text(item.get("path"), point_name),
                "description": _as_text(item.get("description"), ""),
                "prerequisite_candidates": _as_candidate_list(item.get("prerequisite_candidates"), point_name),
                "postrequisite_candidates": _as_candidate_list(item.get("postrequisite_candidates"), point_name),
                "related_candidates": _as_candidate_list(item.get("related_candidates"), point_name),
                "duplicate_candidates": _as_candidate_list(item.get("duplicate_candidates"), point_name),
            }
        )
    if not normalized:
        return {}
    prompt = _PROMPT_KNOWLEDGE_RELATION_DECISION_BATCH.format(
        items_json=json.dumps(normalized, ensure_ascii=False)
    )
    raw = await _call_card_prompt(prompt, model)
    parsed = _parse_summary_json(raw)
    result: dict[str, dict[str, list[str]]] = {}
    parsed_items = parsed.get("items")
    if isinstance(parsed_items, list):
        for item in parsed_items:
            if not isinstance(item, dict):
                continue
            point_id = _as_text(item.get("id"), "")
            if not point_id:
                continue
            current_name = ""
            for n in normalized:
                if n["id"] == point_id:
                    current_name = str(n["name"])
                    break
            result[point_id] = {
                "prerequisite_points": _as_relation_list(item.get("prerequisite_points"), current_name),
                "postrequisite_points": _as_relation_list(item.get("postrequisite_points"), current_name),
                "related_points": _as_relation_list(item.get("related_points"), current_name),
                "duplicate_points": _as_relation_list(item.get("duplicate_points"), current_name)[:3],
            }
    for item in normalized:
        point_id = str(item["id"])
        if point_id in result:
            continue
        result[point_id] = {
            "prerequisite_points": [],
            "postrequisite_points": [],
            "related_points": [],
            "duplicate_points": [],
        }
    return result


async def embed_texts(
    texts: list[str],
    text_type: str = "document",
    model: str | None = None,
    batch_size: int = 8,
) -> list[list[float]]:
    provider = (settings.rag_embedding_provider or "dashscope").strip().lower()
    if provider == "local":
        t0 = time.monotonic()
        try:
            vectors = await embed_texts_local(texts=texts, text_type=text_type)
            elapsed = time.monotonic() - t0
            logger.info("embed_texts 本地完成 | model={} | 向量数={} | 耗时={:.1f}s", settings.local_embedding_model, len(vectors), elapsed)
            return vectors
        except Exception as exc:
            if not settings.local_rag_fallback_remote:
                raise
            logger.warning("embed_texts 本地失败，回退云端 | err={}", exc)
    normalized_texts = [_normalize_embedding_text(t) for t in texts]
    normalized_texts = [t for t in normalized_texts if t]
    if not normalized_texts:
        return []
    model = model or settings.dashscope_embedding_model
    url = f"{settings.dashscope_base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.dashscope_api_key}",
    }
    total = len(normalized_texts)
    batches = (total + batch_size - 1) // batch_size
    logger.info("embed_texts 开始 | model={} | 总句数={} | 批次数={} | text_type={}", model, total, batches, text_type)
    t0 = time.monotonic()
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        for i in range(0, len(normalized_texts), batch_size):
            batch = normalized_texts[i : i + batch_size]
            batch_idx = i // batch_size + 1
            try:
                rows = await _request_embedding_batch(
                    client=client,
                    url=url,
                    headers=headers,
                    model=model,
                    text_type=text_type,
                    batch=batch,
                )
                rows_sorted = sorted(rows, key=lambda x: x.get("index", 0))
                for row in rows_sorted:
                    emb = row.get("embedding", [])
                    vectors.append([float(v) for v in emb])
                logger.debug("embed 批次 {}/{} 成功 ({} 条)", batch_idx, batches, len(batch))
            except httpx.HTTPStatusError as e:
                detail = (e.response.text[:200] if e.response is not None and e.response.text else str(e))
                logger.warning("embed 批次 {}/{} 失败: {}，退化单条重试", batch_idx, batches, detail)
                for text in batch:
                    rows = await _request_embedding_batch(
                        client=client,
                        url=url,
                        headers=headers,
                        model=model,
                        text_type=text_type,
                        batch=[text[:2000]],
                    )
                    emb = rows[0].get("embedding", [])
                    vectors.append([float(v) for v in emb])
    elapsed = time.monotonic() - t0
    logger.info("embed_texts 完成 | 总向量={} | 耗时={:.1f}s", len(vectors), elapsed)
    return vectors


async def rerank_similarity_pairs(
    pairs: list[tuple[str, str]],
    model: str | None = None,
    instruct: str | None = None,
) -> list[float]:
    if not pairs:
        return []
    provider = (settings.rag_rerank_provider or "dashscope").strip().lower()
    if provider == "local":
        t0 = time.monotonic()
        try:
            scores = await rerank_similarity_pairs_local(pairs=pairs)
            elapsed = time.monotonic() - t0
            logger.info("rerank 本地完成 | model={} | score_count={} | 耗时={:.1f}s", settings.local_rerank_model, len(scores), elapsed)
            return scores
        except Exception as exc:
            if not settings.local_rag_fallback_remote:
                raise
            logger.warning("rerank 本地失败，回退云端 | err={}", exc)
    model = model or settings.dashscope_rerank_model
    instruct_text = instruct or settings.rag_query_instruct
    url = f"{settings.dashscope_base_url}/rerank"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.dashscope_api_key}",
    }
    logger.info("rerank 开始 | model={} | pair_count={}", model, len(pairs))
    t0 = time.monotonic()
    scores: list[float] = []
    sdk_module: Any | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
        for idx, (query, document) in enumerate(pairs, start=1):
            try:
                payload = {
                    "model": model,
                    "query": query,
                    "documents": [document],
                    "top_n": 1,
                    "return_documents": False,
                    "instruct": instruct_text,
                }
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                score = _extract_rerank_score(data)
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code != 404:
                    raise
                if sdk_module is None:
                    sdk_module = _load_dashscope_sdk()
                if sdk_module is None:
                    raise
                score = _rerank_score_via_sdk(sdk_module, model, query, document, instruct_text)
            score = max(0.0, min(1.0, score))
            scores.append(score)
            if idx % 20 == 0:
                logger.debug("rerank 进度: {}/{}", idx, len(pairs))
    elapsed = time.monotonic() - t0
    logger.info("rerank 完成 | score_count={} | 耗时={:.1f}s", len(scores), elapsed)
    return scores


def _extract_rerank_score(data: dict[str, Any]) -> float:
    result = data.get("results") or data.get("data") or []
    if not isinstance(result, list) or not result:
        return 0.0
    first = result[0]
    if not isinstance(first, dict):
        return 0.0
    raw = first.get("relevance_score", first.get("score", 0.0))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _load_dashscope_sdk() -> Any | None:
    try:
        module = import_module("dashscope")
        setattr(module, "api_key", settings.dashscope_api_key)
        return module
    except Exception:
        return None


def _rerank_score_via_sdk(
    dashscope_module: Any,
    model: str,
    query: str,
    document: str,
    instruct: str,
) -> float:
    resp = dashscope_module.TextReRank.call(
        model=model,
        query=query,
        documents=[document],
        top_n=1,
        return_documents=False,
        instruct=instruct,
    )
    output = getattr(resp, "output", None)
    if isinstance(output, dict):
        return _extract_rerank_score(output)
    return 0.0


async def _request_embedding_batch(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    model: str,
    text_type: str,
    batch: list[str],
) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model,
        "input": batch,
        "encoding_format": "float",
    }
    logger.debug("embed 请求 | model={} | batch_size={}", model, len(batch))
    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data", [])
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("embedding 响应为空")
    return rows


def _normalize_summary_card(raw: str, force_complexity: str | None = None) -> str:
    parsed = _parse_summary_json(raw)
    complexity = force_complexity or _as_complexity(parsed.get("complexity"))
    card: dict[str, Any] = {
        "version": "v1",
        "complexity": complexity,
        "title": _as_text(parsed.get("title"), "未命名资料"),
        "document_type": _as_text(parsed.get("document_type"), "其他"),
        "summary": _as_text(parsed.get("summary"), "该资料已完成转换，待补充结构化摘要。"),
        "keywords": _as_keywords(parsed.get("keywords")),
        "teaching_value": _as_text(parsed.get("teaching_value"), "可用于课程备课与教学内容组织。"),
    }
    if complexity == "multi_chapter":
        card["structure"] = _as_structure(parsed.get("structure"), min_nodes=1, max_nodes=10, include_boundary=True)
        card["granularity_hint"] = "balanced"
    elif complexity == "single_chapter":
        card["chapter_title"] = _as_text(parsed.get("chapter_title"), "未命名章节")
        card["structure"] = _as_structure(parsed.get("structure"), min_nodes=1, max_nodes=6)
        card["granularity_hint"] = "single"
    else:
        card["key_points"] = _as_flat_key_points(parsed.get("key_points"))
        card["granularity_hint"] = "flat"
    return json.dumps(card, ensure_ascii=False)


def _normalize_embedding_text(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    return cleaned[:2000]


def _parse_summary_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return {}


def _as_complexity(value: Any) -> str:
    if isinstance(value, str) and value in ("multi_chapter", "single_chapter", "flat"):
        return value
    return "flat"


def _as_flat_key_points(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["概括文档主线", "归纳核心概念", "提炼教学重点"]
    points: list[str] = []
    for item in value:
        if isinstance(item, str):
            t = " ".join(item.split())
            if t:
                points.append(t)
        if len(points) == 5:
            break
    if len(points) < 3:
        defaults = ["概括文档主线", "归纳核心概念", "提炼教学重点"]
        for d in defaults:
            if d not in points:
                points.append(d)
            if len(points) >= 3:
                break
    return points[:5]


def _as_text(value: Any, default: str) -> str:
    if isinstance(value, str):
        cleaned = " ".join(value.split())
        return cleaned if cleaned else default
    return default


def _as_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["课程概念", "知识结构", "教学重点", "方法流程", "应用场景"]
    words: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        word = " ".join(item.split())
        if not word or word in seen:
            continue
        words.append(word)
        seen.add(word)
        if len(words) == 5:
            break
    defaults = ["课程概念", "知识结构", "教学重点", "方法流程", "应用场景"]
    i = 0
    while len(words) < 5:
        if defaults[i] not in seen:
            words.append(defaults[i])
            seen.add(defaults[i])
        i += 1
    return words


def _as_structure(value: Any, min_nodes: int = 1, max_nodes: int = 8, include_boundary: bool = False) -> list[dict[str, Any]]:
    fallback: dict[str, Any] = {
        "section": "核心内容",
        "key_points": ["提炼文档主线", "归纳关键知识点"],
    }
    if not isinstance(value, list):
        if include_boundary:
            fallback["first_sentence"] = ""
            fallback["last_sentence"] = ""
        return [fallback]
    result: list[dict[str, Any]] = []
    for node in value:
        if not isinstance(node, dict):
            continue
        section = _as_text(node.get("section"), "")
        if not section:
            continue
        points_raw = node.get("key_points")
        points: list[str] = []
        if isinstance(points_raw, list):
            for p in points_raw:
                if isinstance(p, str):
                    t = " ".join(p.split())
                    if t:
                        points.append(t)
                if len(points) == 4:
                    break
        if len(points) < 2:
            points.extend(["覆盖本节核心概念", "说明本节教学重点"])
        entry: dict[str, Any] = {"section": section, "key_points": points[:4]}
        if include_boundary:
            entry["first_sentence"] = _as_text(node.get("first_sentence"), "")
            entry["last_sentence"] = _as_text(node.get("last_sentence"), "")
        result.append(entry)
        if len(result) == max_nodes:
            break
    if not result:
        if include_boundary:
            fallback["first_sentence"] = ""
            fallback["last_sentence"] = ""
        return [fallback]
    return result


def _as_knowledge_points(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _as_text(item.get("knowledge_point"), "")
        if not name:
            continue
        description = _as_text(item.get("description"), "该知识点用于支撑章节学习。")
        raw_sub = item.get("sub_points")
        sub_points: list[str] = []
        if isinstance(raw_sub, list):
            for sub in raw_sub:
                if isinstance(sub, str):
                    s = " ".join(sub.split())
                    if s and s != name and s not in sub_points:
                        sub_points.append(s)
                if len(sub_points) >= 8:
                    break
        sub_point_descriptions: dict[str, str] = {}
        raw_sub_desc = item.get("sub_point_descriptions")
        if isinstance(raw_sub_desc, dict):
            for sub in sub_points:
                sub_desc = _as_text(raw_sub_desc.get(sub), "")
                if sub_desc:
                    sub_point_descriptions[sub] = sub_desc
        result.append({
            "knowledge_point": name,
            "sub_points": sub_points,
            "description": description,
            "sub_point_descriptions": sub_point_descriptions,
        })
        if len(result) >= 20:
            break
    return result


def _normalize_knowledge_name(value: str) -> str:
    text = re.sub(r"\s+", "", value).lower()
    text = re.sub(r"[，。、“”‘’：；（）\(\)\[\]【】\-—_·,.!?！？:;]", "", text)
    return text


def _merge_knowledge_points(primary: list[dict[str, Any]], supplement: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for item in primary + supplement:
        name = _as_text(item.get("knowledge_point"), "")
        if not name:
            continue
        key = _normalize_knowledge_name(name)
        if not key:
            continue
        sub_points: list[str] = []
        raw_sub_points = item.get("sub_points")
        if isinstance(raw_sub_points, list):
            for sub in raw_sub_points:
                if isinstance(sub, str):
                    s = _as_text(sub, "")
                    if s and s != name and s not in sub_points:
                        sub_points.append(s)
        sub_point_descriptions: dict[str, str] = {}
        raw_sub_desc = item.get("sub_point_descriptions")
        if isinstance(raw_sub_desc, dict):
            for sub in sub_points:
                desc = _as_text(raw_sub_desc.get(sub), "")
                if desc:
                    sub_point_descriptions[sub] = desc
        description = _as_text(item.get("description"), "该知识点用于支撑章节学习。")

        existing = by_key.get(key)
        if not existing:
            current = {
                "knowledge_point": name,
                "sub_points": sub_points,
                "description": description,
                "sub_point_descriptions": sub_point_descriptions,
            }
            by_key[key] = current
            merged.append(current)
            continue

        existing_sub = existing.get("sub_points", [])
        if isinstance(existing_sub, list):
            for sub in sub_points:
                if sub not in existing_sub:
                    existing_sub.append(sub)
            if len(existing_sub) > 8:
                existing_sub[:] = existing_sub[:8]
            existing["sub_points"] = existing_sub
        existing_sub_desc = existing.get("sub_point_descriptions", {})
        if not isinstance(existing_sub_desc, dict):
            existing_sub_desc = {}
        for sub in existing.get("sub_points", []):
            if sub in sub_point_descriptions and sub not in existing_sub_desc:
                existing_sub_desc[sub] = sub_point_descriptions[sub]
        existing["sub_point_descriptions"] = existing_sub_desc
        if len(description) > len(existing.get("description", "")):
            existing["description"] = description
    return merged[:20]


def _as_relation_list(value: Any, current_name: str) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    current_key = _normalize_knowledge_name(current_name)
    for item in value:
        if not isinstance(item, str):
            continue
        name = _as_text(item, "")
        if not name:
            continue
        if _normalize_knowledge_name(name) == current_key:
            continue
        if name in result:
            continue
        result.append(name)
        if len(result) >= 5:
            break
    return result


def _as_candidate_list(value: Any, current_name: str) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    current_key = _normalize_knowledge_name(current_name)
    for item in value:
        if not isinstance(item, str):
            continue
        name = _as_text(item, "")
        if not name:
            continue
        if _normalize_knowledge_name(name) == current_key:
            continue
        if name in result:
            continue
        result.append(name)
        if len(result) >= 12:
            break
    return result
