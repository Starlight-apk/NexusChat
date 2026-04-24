"""
NexusChat 内容安全与风控模块
===========================

提供类似 QQ 的内容安全机制：
- 敏感词过滤（支持多种匹配模式）
- 垃圾消息检测
- 频率异常检测
- 用户行为评分
- ML 模型加载预热（可选）
"""

import re
import time
import asyncio
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class SensitiveWordConfig:
    """敏感词配置"""
    enabled: bool = True
    replace_char: str = "*"
    check_modes: List[str] = field(default_factory=lambda: ["block", "replace"])


@dataclass
class UserBehaviorScore:
    """用户行为评分"""
    score: float = 100.0  # 初始 100 分
    violation_count: int = 0
    last_violation_time: float = 0.0
    message_count: int = 0
    spam_score: float = 0.0  # 垃圾消息评分 0-100
    
    def is_blocked(self) -> bool:
        return self.score < 30 or self.spam_score > 80


class ContentFilter:
    """
    内容过滤器 - 敏感词检测
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.replace_char = self.config.get("replace_char", "*")
        
        # 敏感词库
        self.sensitive_words: Set[str] = set()
        self.sensitive_patterns: List[re.Pattern] = []
        
        # 词组映射（用于替换）
        self.word_replacements: Dict[str, str] = {}
        
        # 加载默认敏感词
        self._load_default_words()
        
        # 从配置加载
        self._load_config_words()
    
    def _load_default_words(self):
        """加载默认敏感词（示例）"""
        # 实际生产中应该从文件或数据库加载大量敏感词
        default_words = {
            "测试敏感词",
            "广告",
            "赌博",
            "诈骗",
        }
        self.sensitive_words.update(default_words)
    
    def _load_config_words(self):
        """从配置加载敏感词"""
        words = self.config.get("words", [])
        self.sensitive_words.update(words)
        
        patterns = self.config.get("patterns", [])
        for pattern in patterns:
            try:
                self.sensitive_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                pass
    
    def add_sensitive_word(self, word: str, replacement: Optional[str] = None):
        """添加敏感词"""
        self.sensitive_words.add(word)
        if replacement:
            self.word_replacements[word] = replacement
    
    def remove_sensitive_word(self, word: str):
        """移除敏感词"""
        self.sensitive_words.discard(word)
        self.word_replacements.pop(word, None)
    
    def load_sensitive_words_from_file(self, filepath: str):
        """从文件加载敏感词（每行一个）"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith("#"):
                        self.sensitive_words.add(word)
        except FileNotFoundError:
            pass
    
    def check(self, content: str) -> Tuple[bool, Optional[str], str]:
        """
        检查内容是否包含敏感词
        
        Returns:
            (is_safe, reason, filtered_content)
        """
        if not self.enabled:
            return True, None, content
        
        filtered = content
        found_words = []
        
        # 检查精确匹配
        for word in self.sensitive_words:
            if word in content:
                found_words.append(word)
                if word in self.word_replacements:
                    filtered = filtered.replace(word, self.word_replacements[word])
                else:
                    filtered = filtered.replace(word, self.replace_char * len(word))
        
        # 检查正则模式
        for pattern in self.sensitive_patterns:
            matches = pattern.findall(content)
            if matches:
                found_words.extend(matches)
                filtered = pattern.sub(self.replace_char * 5, filtered)
        
        if found_words:
            return False, f"包含敏感内容：{', '.join(found_words[:3])}", filtered
        
        return True, None, filtered


class RiskController:
    """
    风控控制器 - 用户行为分析与限制
    
    功能:
    - 用户行为评分
    - 垃圾消息检测
    - 频率异常检测
    - 自动封禁/限制
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 用户行为评分
        self.user_scores: Dict[str, UserBehaviorScore] = defaultdict(UserBehaviorScore)
        
        # 消息历史记录（用于垃圾检测）
        self.recent_messages: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
        
        # 锁
        self._lock = asyncio.Lock()
        
        # 配置
        self.max_message_per_minute = self.config.get("max_message_per_minute", 60)
        self.similar_message_threshold = self.config.get("similar_message_threshold", 0.8)
        self.auto_block_score = self.config.get("auto_block_score", 30)
        
        # 启动清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动风控系统"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """停止风控系统"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def check_user(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        检查用户是否被限制
        
        Returns:
            (allowed, reason)
        """
        async with self._lock:
            score = self.user_scores[user_id]
            
            if score.is_blocked():
                if score.score < 30:
                    return False, f"用户行为评分过低 ({score.score:.1f})，已被限制"
                if score.spam_score > 80:
                    return False, f"疑似垃圾用户 ({score.spam_score:.1f})，已被限制"
            
            return True, None
    
    async def record_message(
        self, 
        user_id: str, 
        content: str,
        is_sensitive: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        记录用户消息并更新评分
        
        Returns:
            (allowed, reason)
        """
        async with self._lock:
            now = time.time()
            score = self.user_scores[user_id]
            
            score.message_count += 1
            
            # 检查是否包含敏感内容
            if is_sensitive:
                score.violation_count += 1
                score.last_violation_time = now
                score.score = max(0, score.score - 20)
                score.spam_score = min(100, score.spam_score + 10)
                
                if score.is_blocked():
                    return False, "发送敏感内容过多，已被限制"
            
            # 记录消息用于垃圾检测
            self.recent_messages[user_id].append((now, content))
            
            # 清理旧消息（保留最近 1 分钟）
            cutoff = now - 60
            self.recent_messages[user_id] = [
                (t, c) for t, c in self.recent_messages[user_id] 
                if t > cutoff
            ]
            
            recent_msgs = self.recent_messages[user_id]
            
            # 检查频率
            if len(recent_msgs) > self.max_message_per_minute:
                score.score = max(0, score.score - 10)
                score.spam_score = min(100, score.spam_score + 5)
                return False, "消息发送过于频繁"
            
            # 检查相似消息（垃圾消息检测）
            if len(recent_msgs) >= 3:
                current_content = content
                similar_count = 0
                
                for _, prev_content in recent_msgs[-10:-1]:  # 检查最近 10 条
                    similarity = self._calculate_similarity(current_content, prev_content)
                    if similarity > self.similar_message_threshold:
                        similar_count += 1
                
                if similar_count >= 3:
                    score.spam_score = min(100, score.spam_score + 15)
                    score.score = max(0, score.score - 5)
                    
                    if score.spam_score > 80:
                        return False, "疑似发送垃圾消息"
            
            # 正常消息，缓慢恢复评分
            if not is_sensitive:
                score.score = min(100, score.score + 0.1)
                score.spam_score = max(0, score.spam_score - 0.5)
            
            return True, None
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度（简单实现）"""
        if not s1 or not s2:
            return 0.0
        
        # 简单的 Jaccard 相似度
        set1 = set(s1)
        set2 = set(s2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    async def report_violation(self, user_id: str, severity: int = 1):
        """举报用户违规"""
        async with self._lock:
            score = self.user_scores[user_id]
            score.violation_count += severity
            score.score = max(0, score.score - severity * 10)
            score.last_violation_time = time.time()
    
    async def restore_user(self, user_id: str):
        """恢复用户评分"""
        async with self._lock:
            if user_id in self.user_scores:
                score = self.user_scores[user_id]
                score.score = 100.0
                score.spam_score = 0.0
                score.violation_count = 0
    
    async def _cleanup_loop(self):
        """定期清理和衰减评分"""
        while True:
            try:
                await asyncio.sleep(300)  # 每 5 分钟
                
                async with self._lock:
                    now = time.time()
                    
                    # 清理长期不活跃用户
                    inactive_threshold = now - 86400  # 24 小时
                    to_remove = []
                    
                    for user_id, score in self.user_scores.items():
                        if (score.last_violation_time < inactive_threshold and
                            score.message_count == 0 and
                            score.score == 100.0):
                            to_remove.append(user_id)
                    
                    for user_id in to_remove:
                        del self.user_scores[user_id]
                        if user_id in self.recent_messages:
                            del self.recent_messages[user_id]
                    
                    # 自然衰减垃圾评分
                    for score in self.user_scores.values():
                        score.spam_score = max(0, score.spam_score - 1)
                        score.score = min(100, score.score + 0.5)
                        
            except asyncio.CancelledError:
                break
            except Exception:
                pass
    
    def get_user_score(self, user_id: str) -> Optional[Dict]:
        """获取用户评分信息"""
        if user_id in self.user_scores:
            score = self.user_scores[user_id]
            return {
                "score": score.score,
                "violation_count": score.violation_count,
                "spam_score": score.spam_score,
                "message_count": score.message_count,
                "is_blocked": score.is_blocked(),
            }
        return None


class SecurityManager:
    """
    统一安全管理器
    
    整合内容过滤和风控系统
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 初始化组件
        filter_config = self.config.get("content_filter", {})
        risk_config = self.config.get("risk_control", {})
        
        self.content_filter = ContentFilter(filter_config)
        self.risk_controller = RiskController(risk_config)
        
        # 统计
        self.stats = {
            "filtered_messages": 0,
            "blocked_users": 0,
            "violations_detected": 0,
        }
    
    async def start(self):
        """启动安全管理系统"""
        await self.risk_controller.start()
    
    async def stop(self):
        """停止安全管理系统"""
        await self.risk_controller.stop()
    
    async def check_and_process_message(
        self,
        user_id: str,
        content: str
    ) -> Tuple[bool, Optional[str], str]:
        """
        检查并处理消息
        
        Returns:
            (allowed, reason, processed_content)
        """
        # 1. 检查用户状态
        allowed, reason = await self.risk_controller.check_user(user_id)
        if not allowed:
            self.stats["blocked_users"] += 1
            return False, reason, content
        
        # 2. 内容过滤检查
        is_safe, filter_reason, filtered_content = self.content_filter.check(content)
        
        if not is_safe:
            self.stats["filtered_messages"] += 1
            self.stats["violations_detected"] += 1
            
            # 记录违规
            await self.risk_controller.record_message(user_id, content, is_sensitive=True)
            
            return False, filter_reason, filtered_content
        
        # 3. 记录正常消息
        allowed, reason = await self.risk_controller.record_message(user_id, content, is_sensitive=False)
        if not allowed:
            return False, reason, content
        
        return True, None, filtered_content
    
    def get_stats(self) -> Dict:
        """获取安全统计"""
        return {
            **self.stats,
            "risk_controller": {
                "tracked_users": len(self.risk_controller.user_scores),
            },
            "content_filter": {
                "sensitive_words_count": len(self.content_filter.sensitive_words),
                "patterns_count": len(self.content_filter.sensitive_patterns),
            }
        }
