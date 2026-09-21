{-# LANGUAGE TemplateHaskell #-}

module Main where

import Control.Monad (unless)
import Language.Haskell.TH (integerL, litE)

answer :: Int
answer = $(litE (integerL 42))

main :: IO ()
main = do
  unless (answer == 42) $ fail "Template Haskell returned the wrong value"
  putStrLn "Native Template Haskell passed"
