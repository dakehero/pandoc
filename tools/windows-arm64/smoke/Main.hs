{-# LANGUAGE ForeignFunctionInterface #-}

module Main where

import Control.Exception (bracket)
import Control.Monad (unless)
import Foreign (FunPtr, freeHaskellFunPtr)
import Foreign.C.Types (CInt (..))

type Callback = CInt -> IO CInt

foreign import ccall "wrapper"
  makeCallback :: Callback -> IO (FunPtr Callback)

foreign import ccall safe "invoke_callback"
  invokeCallback :: FunPtr Callback -> CInt -> IO CInt

main :: IO ()
main = do
  bracket (makeCallback (pure . (* 2))) freeHaskellFunPtr $ \callback -> do
    result <- invokeCallback callback 21
    unless (result == 42) $ fail "C/Haskell callback returned the wrong value"
  putStrLn "Native C and Haskell callback passed"
