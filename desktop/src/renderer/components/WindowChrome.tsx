interface Props {
  children: React.ReactNode;
}

export function WindowChrome({ children }: Props) {
  return (
    <div className="relative flex h-full w-full flex-col bg-paper">{children}</div>
  );
}
