"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

export type ThemeProviderProps = ComponentProps<typeof NextThemesProvider>;

export const ThemeProvider = (props: ThemeProviderProps) => <NextThemesProvider {...props} />;
