{-# LANGUAGE ForeignFunctionInterface #-}
{-# LANGUAGE TemplateHaskell #-}

module Main where

import Control.Exception (bracket)
import Control.Monad (unless)
import Foreign (FunPtr, freeHaskellFunPtr)
import Foreign.C.Types (CInt (..))
import Language.Haskell.TH (integerL, litE)

type Callback = CInt -> IO CInt

foreign import ccall "wrapper"
  makeCallback :: Callback -> IO (FunPtr Callback)

foreign import ccall safe "invoke_callback"
  invokeCallback :: FunPtr Callback -> CInt -> IO CInt

answer :: Int
answer = $(litE (integerL 42))

main :: IO ()
main = do
  unless (answer == 42) $ fail "Template Haskell returned the wrong value"
  bracket (makeCallback (pure . (* 2))) freeHaskellFunPtr $ \callback -> do
    result <- invokeCallback callback 21
    unless (result == 42) $ fail "C/Haskell callback returned the wrong value"
  putStrLn "Native GHC compilation, Template Haskell and C FFI passed"
