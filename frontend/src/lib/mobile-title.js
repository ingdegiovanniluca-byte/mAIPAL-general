import { createContext, useContext } from "react";

// Lets a page append a short suffix to the section name in the mobile top bar
// (e.g. "Task 2026"). The layout provides the setter; pages clear it on unmount.
export const MobileTitleContext = createContext(() => {});
export const useSetMobileTitleSuffix = () => useContext(MobileTitleContext);
