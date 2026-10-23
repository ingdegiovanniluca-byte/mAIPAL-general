import { createContext, useContext } from "react";

/* The desktop split (from MOBILE_BREAKPOINT up): the chat always in the left column, the section
   chosen in the header on the right. The chat there stays mounted while the route changes for
   the right side, so what other pages ask of it ("Chiedi a Help", "Nuova azione", a task's
   conversation) reaches it as an `intent` - the state they would have navigated to the chat
   with - instead of through the route. */
export const ChatPaneContext = createContext(null);   // { intent: {...state, nonce} | null } inside the column
export const useChatPane = () => useContext(ChatPaneContext);

// Where the bottom sheets open: inside the chat column (its own element), else the whole window.
export const SheetHostContext = createContext(null);
