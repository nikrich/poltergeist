interface Props {
  count?: number;
  height?: number;
}

export function SkeletonRows({ count = 3, height = 32 }: Props) {
  return (
    <div className="flex flex-col gap-1 p-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-sm bg-fog/40"
          style={{ height }}
        />
      ))}
    </div>
  );
}
