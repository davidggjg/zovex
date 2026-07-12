import { NetflixRow } from "./home/NetflixCard";

// כרטיסיות השידורים החיים — מוצגות כשורה ראשונה בעמוד הבית כשיש שידורים פעילים
export default function LiveBanner({ liveChannels, onPlay, isDesktop }) {
  if (!liveChannels || liveChannels.length === 0) return null;
  return (
    <NetflixRow
      title="👁️ שידורים חיים"
      items={liveChannels}
      isDesktop={isDesktop}
      handleItemClick={onPlay}
      isLiveRow={true}
    />
  );
}
