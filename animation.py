"""Read the existing animation manifest and locate available frame sequences."""

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Clip:
    id: str
    name: str
    fps: int
    loop: bool
    frames: tuple[Path, ...]

    def frame_index(self, elapsed_seconds: float) -> int:
        index = max(0, int(elapsed_seconds * self.fps))
        return index % len(self.frames) if self.loop else min(index, len(self.frames) - 1)


@dataclass(frozen=True)
class AnimationLibrary:
    canvas_width: int
    canvas_height: int
    character_height: int
    ground_y: int
    clip: Clip

    @classmethod
    def load(cls, project_root: Path, allow_placeholder: bool = False) -> "AnimationLibrary":
        animations = (project_root / "animations").resolve()
        manifest = json.loads((animations / "manifest.json").read_text(encoding="utf-8"))
        dimensions = tuple(int(manifest[key]) for key in (
            "CanvasWidth", "CanvasHeight", "CharacterHeight", "GroundY"
        ))
        if any(value <= 0 for value in dimensions):
            raise ValueError("动画尺寸和地面位置必须大于零")

        available: dict[str, Clip] = {}
        for entry in manifest["Clips"]:
            fps = int(entry["Fps"])
            if not 1 <= fps <= 60:
                raise ValueError(f"无效帧率: {entry['Id']}")
            folder = (animations / entry["Folder"]).resolve()
            if not folder.is_relative_to(animations) or folder == animations:
                raise ValueError(f"动作目录越界: {entry['Id']}")
            frames = tuple(sorted(folder.glob("frame-*.png"))) if folder.is_dir() else ()
            if frames:
                available[entry["Id"]] = Clip(
                    entry["Id"], entry["Name"], fps, bool(entry["Loop"]), frames
                )

        clip = available.get(manifest["DefaultClip"])
        if clip is None:
            if allow_placeholder:
                clip = Clip("placeholder", "Demo placeholder", 24, True,
                            tuple(Path(f"placeholder-{index}") for index in range(22)))
        if clip is None:
            clip = available.get("idle") or next(iter(available.values()), None)
        if clip is None:
            raise ValueError("没有可播放的 PNG 动画")
        return cls(*dimensions, clip)
