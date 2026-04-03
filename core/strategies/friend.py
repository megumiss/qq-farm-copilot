"""P4 社交 — 好友巡查/帮忙/偷菜/同意好友"""
import time
from loguru import logger

from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.scene_detector import Scene, identify_scene
from core.strategies.base import BaseStrategy, StrategyResult


class FriendStrategy(BaseStrategy):
    requires_page = {"main", "friend"}
    expected_page_after = {"main", "friend"}

    def try_friend_help(self, rect: tuple, detections: list[DetectResult]) -> list[str]:
        """检测好友求助并进入帮忙"""
        btn = self.find_by_name(detections, "btn_friend_help")
        if not btn:
            return []
        self.click(btn.x, btn.y, "好友求助")
        self.sleep(0.5)
        return self._help_in_friend_farm(rect)

    def _help_in_friend_farm(self, rect: tuple) -> list[str]:
        """在好友家园执行帮忙操作"""
        actions_done = []
        for _ in range(10):
            if self.stopped:
                break
            cv_img, dets, _ = self.capture(rect)
            if cv_img is None:
                break

            scene = identify_scene(dets, self.cv_detector, cv_img)

            if scene == Scene.FRIEND_FARM:
                acted = False
                for btn_name, desc, action_type in [
                    ("btn_water", "帮好友浇水", ActionType.HELP_WATER),
                    ("btn_weed", "帮好友除草", ActionType.HELP_WEED),
                    ("btn_bug", "帮好友除虫", ActionType.HELP_BUG),
                ]:
                    btn = self.find_by_name(dets, btn_name)
                    if btn:
                        self.click(btn.x, btn.y, desc, action_type)
                        actions_done.append(desc)
                        acted = True
                        self.sleep(0.3)
                        break

                if not acted:
                    home = self.find_by_name(dets, "btn_home")
                    if home:
                        self.click(home.x, home.y, "回家")
                        actions_done.append("回家")
                        self.sleep(0.3)
                    break

            elif scene == Scene.POPUP:
                self.handle_basic_popup(dets)
                self.sleep(0.3)
            elif scene == Scene.FARM_OVERVIEW:
                break
            else:
                self.sleep(0.3)

        return actions_done

    def try_steal(self, rect: tuple) -> str | None:
        """自动偷菜（待实现：需要进入好友农场检测成熟作物）"""
        # TODO: 好友列表 → 进入 → 检测成熟 → 偷菜 → 回家
        return None

    def try_accept_friend(self, detections: list[DetectResult]) -> str | None:
        """自动同意好友申请（待实现：需要 btn_accept_friend 模板）"""
        # TODO: 检测好友申请弹窗 → 点击同意
        return None

    def run_once(self, rect: tuple, detections: list[DetectResult], **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.try_friend_help(rect, detections))

