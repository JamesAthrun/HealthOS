export type FormProps<T> = {
  /** 编辑时传入原记录；新建时为 null */
  initial: T | null;
  /** 在“记录”页补录其他日期时，用来设置默认时间（yyyy-mm-dd） */
  day?: string;
  /** 保存或删除成功后调用，由外层关闭面板、提示并刷新；undo 用于删除后的“撤销” */
  onDone: (message: string, tone?: "success" | "warning", undo?: () => Promise<unknown>) => void;
};
